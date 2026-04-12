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
    
    def get_agent_keys(self) -> List[str]:
        """Get list of all agent keys"""
        return list(self._agents.keys())
    
    def update_weight(self, agent_key: str, new_weight: float):
        """Update agent weight"""
        if agent_key in self._agents:
            self._agents[agent_key].update_weight(new_weight)
            self._weights[agent_key] = new_weight
            logger.info("Updated agent weight", agent=agent_key, weight=new_weight)
    
    def get_weights(self) -> Dict[str, float]:
        """Get current weights for all agents"""
        return self._weights.copy()
    
    def load_weights_from_config(self, config_path: Optional[str] = None):
        """Load agent weights from configuration file"""
        if config_path is None:
            config_path = os.path.join("config", "agent_weights.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    weights = json.load(f)
                
                for agent_key, weight in weights.items():
                    if agent_key in self._agents:
                        self.update_weight(agent_key, weight)
                
                logger.info("Loaded weights from config", config_path=config_path)
            except Exception as e:
                logger.error("Error loading weights", error=str(e))
        else:
            logger.warning("Weights config not found, using default weights", config_path=config_path)
    
    def save_weights_to_config(self, config_path: Optional[str] = None):
        """Save current weights to configuration file"""
        if config_path is None:
            config_path = os.path.join("config", "agent_weights.json")
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        try:
            with open(config_path, 'w') as f:
                json.dump(self._weights, f, indent=2)
            logger.info("Saved weights to config", config_path=config_path)
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

