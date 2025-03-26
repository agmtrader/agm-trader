from abc import ABC
import datetime
from ib_insync import  *

class BaseStrategyParams(ABC):
    def __init__(self):
        self.position = 0
        self.historicalData = {}
        self.openOrders = []
        self.executedOrders = []
        self.contracts = []
        self.positions = []

    def to_dict(self):

        # Convert datetime columns to strings in historicalData
        for symbol, data in self.historicalData.items():
            for entry in data:
                if 'date' in entry and (isinstance(entry['date'], datetime.date) or isinstance(entry['date'], datetime.datetime)):  # Change 'datetime_column' to 'date'
                    entry['date'] = entry['date'].strftime('%Y-%m-%d %H:%M:%S')  # Format as needed
        
        return {
            'position': self.position,
            'historical_data': self.historicalData,
            'open_orders': self.openOrders,
            'executed_orders': self.executedOrders,
            'contracts': [contract.dict() for contract in self.contracts],
            'positions': self.positions
        }

class IchimokuBaseParams(BaseStrategyParams):
    def __init__(self):
        super().__init__()
        mes = Future('MES', '202506', 'CME')
        mym = Future('MYM', '202506', 'CBOT')
        self.contracts = [mes, mym]
        self.tenkan = 0
        self.kijun = 0
        self.number_of_contracts = 0
        self.psar_mes = []
        self.psar_mym = []
        
    def to_dict(self):
        ichimoku_dict = {
            'tenkan': self.tenkan,
            'kijun': self.kijun,
            'number_of_contracts': self.number_of_contracts,
            'psar_mes': self.psar_mes,
            'psar_mym': self.psar_mym
        }
        return {
            **ichimoku_dict,
            **super().to_dict()
        }