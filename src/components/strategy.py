from src.lib.params import BaseStrategyParams, BullSpreadParams
from abc import ABC, abstractmethod
from ib_insync import *

class Strategy(ABC):
    def __init__(self, initialParams: BaseStrategyParams):
        self.params = initialParams
    
    @abstractmethod
    def run(self):
        pass

    def to_dict(self):
        return {
            'params': self.params.to_dict()
        }

class BullSpread(Strategy):
    def __init__(self, initialParams: BullSpreadParams):
        super().__init__(initialParams)
    
    def run(self):
        sma = 0
        pricesSum = 0
        for day in self.params.historicalData:
            pricesSum += day['close']

        sma = pricesSum/len(self.params.historicalData)
        sma = round(sma, 2)

        if len(self.params.openOrders) != 0:
            return 'STAY'
        
        if self.params.position == 0:
            if (self.params.latestPrice > sma and self.params.latestPrice != 0):
                return 'BUY'
            else:
                return 'STAY'
        elif self.params.position > 0:
            if (self.params.latestPrice < sma and self.params.latestPrice != 0):
                return 'SELL'
            else:
                return 'STAY'
        else:
            return 'STAY'
        
    def create_order(self, action: str):
        if action == 'BUY':
            return MarketOrder(action='BUY', totalQuantity=1)
        elif action == 'SELL':
            return MarketOrder(action='SELL', totalQuantity=1)
        else:
            return None
