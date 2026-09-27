"""Growth quality backtest engine - concentrated liquid quality/growth equity.

Also includes live trading momentum selector (Arm C style).
"""

from src.backtesting.growth_quality.engine import GrowthQualityBacktest
from src.backtesting.growth_quality.universe import (
    get_qqq_universe,
    get_hindsight_quality_basket,
    get_point_in_time_quality_universe,
    get_sp100_equal_weight_universe,
    get_universe_for_arm,
)
from src.backtesting.growth_quality.momentum import MomentumSelector

__all__ = [
    "GrowthQualityBacktest",
    "get_qqq_universe",
    "get_hindsight_quality_basket",
    "get_point_in_time_quality_universe",
    "get_sp100_equal_weight_universe",
    "get_universe_for_arm",
    "MomentumSelector",
]
