from abc import ABC, abstractmethod
from src.lib.params import BaseStrategyParams
from abc import ABC, abstractmethod
from ib_insync import *

class Strategy(ABC):
    def __init__(self, initialParams: BaseStrategyParams):
        self.params = initialParams
        self.timeframe = '1 day'
        self.timeframe_seconds = 86400
    
    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def create_orders(self, action: str):
        pass

    @abstractmethod
    def refresh_params(self, data_manager):
        """Refresh internal parameters using the supplied DataManager instance."""
        pass

    @abstractmethod
    def backtest(self):
        pass

    def to_dict(self):
        return {
            'params': self.params.to_dict()
        }

    def has_open_position(self):
        """Return True if any open position is currently held (long or short)."""
        for pos in getattr(self.params, 'positions', []):
            if abs(pos.get('position', 0)) > 0:
                return True
        return False
