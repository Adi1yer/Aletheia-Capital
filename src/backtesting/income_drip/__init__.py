"""Income drip strategies - dividend and covered call premiums dripped into momentum growth.

Also includes live trading dividend ballast selector and drip manager.
"""

from src.backtesting.income_drip.ballast import DividendBallastSelector
from src.backtesting.income_drip.drip import DividendDripManager

__all__ = [
    "DividendBallastSelector",
    "DividendDripManager",
]
