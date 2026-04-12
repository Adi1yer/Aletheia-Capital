"""Initialize and register all agents"""

from src.agents.registry import get_registry
from src.agents.warren_buffett import WarrenBuffettAgent
from src.agents.aswath_damodaran import AswathDamodaranAgent
from src.agents.ben_graham import BenGrahamAgent
from src.agents.bill_ackman import BillAckmanAgent
from src.agents.cathie_wood import CathieWoodAgent
from src.agents.charlie_munger import CharlieMungerAgent
from src.agents.michael_burry import MichaelBurryAgent
from src.agents.mohnish_pabrai import MohnishPabraiAgent
from src.agents.peter_lynch import PeterLynchAgent
from src.agents.phil_fisher import PhilFisherAgent
from src.agents.rakesh_jhunjhunwala import RakeshJhunjhunwalaAgent
from src.agents.stanley_druckenmiller import StanleyDruckenmillerAgent
from src.agents.valuation_analyst import ValuationAnalystAgent
from src.agents.sentiment_analyst import SentimentAnalystAgent
from src.agents.fundamentals_analyst import FundamentalsAnalystAgent
from src.agents.technicals_analyst import TechnicalsAnalystAgent
from src.agents.growth_analyst import GrowthAnalystAgent
from src.agents.news_sentiment_analyst import NewsSentimentAnalystAgent
from src.agents.aditya_iyer import AdityaIyerAgent
from src.agents.chamath_palihapitiya import ChamathPalihapitiyaAgent
from src.agents.ron_baron import RonBaronAgent
from src.agents.congressional_trader import CongressionalTraderAgent
import structlog

logger = structlog.get_logger()


def initialize_agents():
    """Initialize and register all agents with default weights"""
    registry = get_registry()
    
    # Default weights (from original GitHub repo)
    # These will be adjusted based on performance over time
    default_weights = {
        'warren_buffett': 1.0,
        'aswath_damodaran': 1.0,
        'ben_graham': 1.0,
        'bill_ackman': 1.0,
        'cathie_wood': 1.0,
        'charlie_munger': 1.0,
        'michael_burry': 1.0,
        'mohnish_pabrai': 1.0,
        'peter_lynch': 1.0,
        'phil_fisher': 1.0,
        'rakesh_jhunjhunwala': 1.0,
        'stanley_druckenmiller': 1.0,
        'valuation_analyst': 1.0,
        'sentiment_analyst': 1.0,
        'fundamentals_analyst': 1.0,
        'technicals_analyst': 1.0,
        'growth_analyst': 1.0,
        'news_sentiment_analyst': 1.0,
        'aditya_iyer': 1.0,
        'chamath_palihapitiya': 1.0,
        'ron_baron': 1.0,
        'congressional_trader': 1.0,
    }
    
    # Register all agents
    registry.register(WarrenBuffettAgent(weight=default_weights.get('warren_buffett', 1.0)))
    registry.register(AswathDamodaranAgent(weight=default_weights.get('aswath_damodaran', 1.0)))
    registry.register(BenGrahamAgent(weight=default_weights.get('ben_graham', 1.0)))
    registry.register(BillAckmanAgent(weight=default_weights.get('bill_ackman', 1.0)))
    registry.register(CathieWoodAgent(weight=default_weights.get('cathie_wood', 1.0)))
    registry.register(CharlieMungerAgent(weight=default_weights.get('charlie_munger', 1.0)))
    registry.register(MichaelBurryAgent(weight=default_weights.get('michael_burry', 1.0)))
    registry.register(MohnishPabraiAgent(weight=default_weights.get('mohnish_pabrai', 1.0)))
    registry.register(PeterLynchAgent(weight=default_weights.get('peter_lynch', 1.0)))
    registry.register(PhilFisherAgent(weight=default_weights.get('phil_fisher', 1.0)))
    registry.register(RakeshJhunjhunwalaAgent(weight=default_weights.get('rakesh_jhunjhunwala', 1.0)))
    registry.register(StanleyDruckenmillerAgent(weight=default_weights.get('stanley_druckenmiller', 1.0)))
    registry.register(ValuationAnalystAgent(weight=default_weights.get('valuation_analyst', 1.0)))
    registry.register(SentimentAnalystAgent(weight=default_weights.get('sentiment_analyst', 1.0)))
    registry.register(FundamentalsAnalystAgent(weight=default_weights.get('fundamentals_analyst', 1.0)))
    registry.register(TechnicalsAnalystAgent(weight=default_weights.get('technicals_analyst', 1.0)))
    registry.register(GrowthAnalystAgent(weight=default_weights.get('growth_analyst', 1.0)))
    registry.register(NewsSentimentAnalystAgent(weight=default_weights.get('news_sentiment_analyst', 1.0)))
    registry.register(AdityaIyerAgent(weight=default_weights.get('aditya_iyer', 1.0)))
    registry.register(ChamathPalihapitiyaAgent(weight=default_weights.get('chamath_palihapitiya', 1.0)))
    registry.register(RonBaronAgent(weight=default_weights.get('ron_baron', 1.0)))
    registry.register(CongressionalTraderAgent(weight=default_weights.get('congressional_trader', 1.0)))

    logger.info("Agents initialized", agent_count=len(registry.get_all()))
    
    # Load weights from config if available
    registry.load_weights_from_config()
    
    return registry

