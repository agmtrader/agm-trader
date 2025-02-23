from abc import ABC
import datetime

class BaseStrategyParams(ABC):
    def __init__(self, name: str, ticker: str, latestPrice: float, position: int, historicalData: list, openOrders: list, executedOrders: list):
        self.name = name
        self.ticker = ticker
        self.latestPrice = latestPrice
        self.position = position
        self.historicalData = historicalData
        self.openOrders = openOrders
        self.executedOrders = executedOrders

    def to_dict(self):
        # Convert datetime columns to strings in historicalData
        for entry in self.historicalData:
            if 'date' in entry and isinstance(entry['date'], datetime.datetime):  # Change 'datetime_column' to 'date'
                entry['date'] = entry['date'].strftime('%Y-%m-%d %H:%M:%S')  # Format as needed
        
        return {
            'name': self.name,
            'ticker': self.ticker,
            'latestPrice': self.latestPrice,
            'position': self.position,
            'historicalData': self.historicalData,
            'openOrders': self.openOrders,
            'executedOrders': self.executedOrders
        }

class BullSpreadParams(BaseStrategyParams):
    def __init__(self, ticker: str, latestPrice: float, position: int, historicalData: list, openOrders: list, executedOrders: list):
        super().__init__('Bull Spread', ticker, latestPrice, position, historicalData, openOrders, executedOrders)