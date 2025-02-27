from abc import ABC
import datetime
from ib_insync import  *

class BaseStrategyParams(ABC):
    def __init__(self):
        self.position = 0
        self.historicalData = {}
        self.openOrders = []
        self.executedOrders = []

    def to_dict(self):
        # Convert datetime columns to strings in historicalData
        for symbol, data in self.historicalData.items():
            for entry in data:
                if 'date' in entry and (isinstance(entry['date'], datetime.date) or isinstance(entry['date'], datetime.datetime)):  # Change 'datetime_column' to 'date'
                    entry['date'] = entry['date'].strftime('%Y-%m-%d %H:%M:%S')  # Format as needed
        
        return {
            'position': self.position,
            'historicalData': self.historicalData,
            'openOrders': self.openOrders,
            'executedOrders': self.executedOrders
        }

class IchimokuBaseParams(BaseStrategyParams):
    def __init__(self):
        super().__init__()
        mes = Future('MES', '202503', 'CME')
        mym = Future('MYM', '202503', 'CBOT')
        self.contracts = [mes, mym]
        self.tenkan = 0
        self.kijun = 0
        self.current_psar_mes = 0
        self.current_psar_mym = 0
        self.number_of_contracts = 0
        
    def to_dict(self):
        ichimoku_dict = {
            'contracts': [contract.dict() for contract in self.contracts],
            'tenkan': self.tenkan,
            'kijun': self.kijun,
            'current_psar_mes': self.current_psar_mes,
            'current_psar_mym': self.current_psar_mym,
            'number_of_contracts': self.number_of_contracts
        }
        return {
            **ichimoku_dict,
            **super().to_dict()
        }