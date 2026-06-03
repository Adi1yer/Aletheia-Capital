"""Agent registry for dynamic agent loading and management"""

from typing import Dict, List, Optional
from src.agents.base import BaseAgent
import structlog
import json
import os

logger = structlog.get_logger()


class AgentRegistry:
    """Registry for managing all investment agents"""

    def __init__(self):
        """Initialize registry"""
        self._agents: Dict[str, BaseAgent] = {}
        self._weights: Dict[str, float] = {}
        self._regime_weights: Dict[str, Dict[str, float]] = {}
        self._regime_blend: float = 0.7
        logger.info("Initialized agent registry")

    def register(self, agent: BaseAgent):
        """Register an agent"""
        agent_key = agent.name.lower().replace(" ", "_")
        self._agents[agent_key] = agent
        self._weights[agent_key] = agent.weight
        logger.info("Registered agent", agent=agent.name, key=agent_key, weight=agent.weight)

    def get(self, agent_key: str) -> Optional[BaseAgent]:
        """Get agent by key"""
        return self._agents.get(agent_key)

    def get_all(self) -> Dict[str, BaseAgent]:
        """Get all registered agents"""
        return self._agents.copy()

    def get_active(
        self, active_keys: Optional[List[str]] = None
    ) -> Dict[str, BaseAgent]:
        """Return registered agents filtered to active_keys (all if None)."""
        if not active_keys:
            return self.get_all()
        key_set = set(active_keys)
        return {k: a for k, a in self._agents.items() if k in key_set}

    def get_agent_keys(self) -> List[str]:
        """Get list of all agent keys"""
        return list(self._agents.keys())

    def update_weight(self, agent_key: str, new_weight: float, regime_mode: Optional[str] = None):
        """Update agent weight (global and optionally regime bucket)."""
        if agent_key in self._agents:
            if regime_mode:
                bucket = self._regime_weights.setdefault(regime_mode, {})
                bucket[agent_key] = new_weight
            else:
                self._agents[agent_key].update_weight(new_weight)
                self._weights[agent_key] = new_weight
            logger.info("Updated agent weight", agent=agent_key, weight=new_weight, regime=regime_mode)

    def get_weights(self, regime_mode: Optional[str] = None) -> Dict[str, float]:
        """Get blended weights for all agents (global + regime when available)."""
        if not regime_mode or regime_mode not in self._regime_weights:
            return self._weights.copy()
        reg = self._regime_weights.get(regime_mode) or {}
        alpha = self._regime_blend
        out: Dict[str, float] = {}
        for ak, gw in self._weights.items():
            rw = reg.get(ak, gw)
            out[ak] = round(alpha * rw + (1.0 - alpha) * gw, 4)
        return out

    def load_weights_from_config(self, config_path: Optional[str] = None):
        """Load agent weights from configuration file (legacy flat or regime schema)."""
        if config_path is None:
            config_path = os.path.join("config", "agent_weights.json")

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "global" in data:
                    for agent_key, weight in (data.get("global") or {}).items():
                        if agent_key in self._agents:
                            self.update_weight(agent_key, float(weight))
                    self._regime_weights = {
                        k: {ak: float(w) for ak, w in v.items()}
                        for k, v in (data.get("by_regime") or {}).items()
                        if isinstance(v, dict)
                    }
                    self._regime_blend = float(data.get("regime_blend", 0.7))
                else:
                    for agent_key, weight in data.items():
                        if agent_key in self._agents:
                            self.update_weight(agent_key, float(weight))

                logger.info("Loaded weights from config", config_path=config_path)
            except Exception as e:
                logger.error("Error loading weights", error=str(e))
        else:
            logger.warning("Weights config not found, using default weights", config_path=config_path)

    def save_weights_to_config(
        self,
        config_path: Optional[str] = None,
        regime_mode: Optional[str] = None,
    ):
        """Save current weights to configuration file."""
        if config_path is None:
            config_path = os.path.join("config", "agent_weights.json")

        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        payload: Dict = {
            "global": dict(self._weights),
            "by_regime": dict(self._regime_weights),
            "regime_blend": self._regime_blend,
        }

        try:
            with open(config_path, "w") as f:
                json.dump(payload, f, indent=2)
            logger.info("Saved weights to config", config_path=config_path, regime=regime_mode)
        except Exception as e:
            logger.error("Error saving weights", error=str(e))


# Global registry instance
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """Get global agent registry"""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
