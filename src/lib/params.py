from abc import ABC
import datetime
from ib_insync import *
from typing import List, Dict, Any, Optional

class ContractData:
    """Class to hold an IB contract and its associated historical market data"""
    
    def __init__(self, contract: Contract, data: Optional[List[Dict[str, Any]]] = None):
        self.contract = contract
        self.data = data or []
        self.indicators = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        # Convert datetime columns to strings in data
        formatted_data = []
        for entry in self.data:
            formatted_entry = entry.copy()
            if 'date' in formatted_entry and (isinstance(formatted_entry['date'], datetime.date) or isinstance(formatted_entry['date'], datetime.datetime)):
                formatted_entry['date'] = formatted_entry['date'].strftime('%Y-%m-%d %H:%M:%S')
            formatted_data.append(formatted_entry)
        
        # Create a safe contract representation
        contract_info = {
            'symbol': self.contract.symbol,
            'secType': self.contract.secType,
            'exchange': self.contract.exchange,
            'currency': getattr(self.contract, 'currency', 'USD'),
            'lastTradeDateOrContractMonth': getattr(self.contract, 'lastTradeDateOrContractMonth', ''),
        }
        
        return {
            'contract': contract_info,
            'data': formatted_data,
            'symbol': self.contract.symbol,
            'indicators': self.indicators,
        }

class BaseStrategyParams(ABC):
    def __init__(self):
        self.contracts: List[ContractData] = []
        self.open_orders: List[Dict[str, Any]] = []
        self.executed_orders: List[Dict[str, Any]] = []
        self.positions: List[Any] = []
        self.indicators: Dict[str, Any] = {}

    def get_data_by_symbol(self, symbol: str) -> Optional[ContractData]:
        """Get contract data by symbol"""
        for contract_data in self.contracts:
            if contract_data.contract.symbol == symbol:
                return contract_data
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'contracts': [contract_data.to_dict() for contract_data in self.contracts],
            'open_orders': self.open_orders,
            'executed_orders': self.executed_orders,
            'positions': self.positions,
            'indicators': self.indicators,
        }

class IchimokuBaseParams(BaseStrategyParams):
    def __init__(self):
        super().__init__()

        # For simplicity, use March 2025 contracts (you may want to implement auto-rolling logic)
        contract_month = '202509'
        
        mes_contract = Future('MES', contract_month, 'CME')
        mym_contract = Future('MYM', contract_month, 'CBOT')
        
        self.contracts = [
            ContractData(mes_contract),
            ContractData(mym_contract)
        ]
        
        self.tenkan: float = 0
        self.kijun: float = 0
        self.number_of_contracts: int = 0
        
    def get_mes_data(self) -> Optional[ContractData]:
        """Get MES contract data"""
        return self.get_data_by_symbol('MES')
    
    def get_mym_data(self) -> Optional[ContractData]:
        """Get MYM contract data"""
        return self.get_data_by_symbol('MYM')
        
    def to_dict(self) -> Dict[str, Any]:
        ichimoku_dict = {
            'tenkan': self.tenkan,
            'kijun': self.kijun,
            'number_of_contracts': self.number_of_contracts,
        }
        return {
            **ichimoku_dict,
            **super().to_dict()
        }

class SMACrossoverParams(BaseStrategyParams):
    """Parameters container for the SMA crossover strategy"""

    def __init__(self):
        super().__init__()
        aapl_contract = Stock('AAPL', 'SMART', 'USD')
        self.contracts = [ContractData(aapl_contract)]
        self.indicators = {
            'sma': 0
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'indicators': self.indicators,
            **super().to_dict(),
        }