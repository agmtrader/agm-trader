from abc import ABC
import datetime
from ib_insync import *
from typing import List, Dict, Any, Optional

class ContractData:
    """Class to hold an IB contract and its associated historical market data"""
    
    def __init__(self, contract: Contract, data: Optional[List[Dict[str, Any]]] = None):
        self.contract = contract
        self.data = data or []
        
    def has_data(self) -> bool:
        """Check if historical data is available"""
        return len(self.data) > 0
    
    def get_latest_price(self) -> Optional[float]:
        """Get the latest close price from historical data"""
        if self.has_data():
            return self.data[-1].get('close')
        return None
    
    def get_symbol(self) -> str:
        """Get the contract symbol"""
        return self.contract.symbol
    
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
            'symbol': self.get_symbol(),
            'has_data': self.has_data(),
            'data_points': len(self.data)
        }

class BaseStrategyParams(ABC):
    def __init__(self):
        self.contracts: List[ContractData] = []
        self.open_orders: List[Dict[str, Any]] = []
        self.executed_orders: List[Dict[str, Any]] = []
        self.positions: List[Any] = []

    def get_contract_by_symbol(self, symbol: str) -> Optional[ContractData]:
        """Get contract data by symbol"""
        for contract_data in self.contracts:
            if contract_data.get_symbol() == symbol:
                return contract_data
        return None

    def get_position_count(self) -> int:
        """Get the number of positions"""
        return len(self.positions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'contracts': [contract_data.to_dict() for contract_data in self.contracts],
            'open_orders': self.open_orders,
            'executed_orders': self.executed_orders,
            'positions': self.positions,
            'position_count': self.get_position_count()
        }

class IchimokuBaseParams(BaseStrategyParams):
    def __init__(self):
        super().__init__()
        # Create contract data objects for MES and MYM (using front month contracts)
        # Get current date to determine appropriate contract month
        current_date = datetime.datetime.now()
        
        # For simplicity, use March 2025 contracts (you may want to implement auto-rolling logic)
        contract_month = '202509'  # June 2025
        
        mes_contract = Future('MES', contract_month, 'CME')
        mym_contract = Future('MYM', contract_month, 'CBOT')
        
        self.contracts = [
            ContractData(mes_contract),
            ContractData(mym_contract)
        ]
        
        self.tenkan: float = 0
        self.kijun: float = 0
        self.number_of_contracts: int = 0
        self.psar_mes: List[float] = []
        self.psar_mym: List[float] = []
        self.psar_difference: float = 0  # Store PSAR difference for TP calculations
        self.simulated_mym: List[Dict[str, Any]] = []  # Store MYM simulation data
        self.stop_loss_updates: List[Dict[str, Any]] = []  # Store stop loss updates
        
    def get_mes_data(self) -> Optional[ContractData]:
        """Get MES contract data"""
        return self.get_contract_by_symbol('MES')
    
    def get_mym_data(self) -> Optional[ContractData]:
        """Get MYM contract data"""
        return self.get_contract_by_symbol('MYM')
        
    def to_dict(self) -> Dict[str, Any]:
        ichimoku_dict = {
            'tenkan': self.tenkan,
            'kijun': self.kijun,
            'number_of_contracts': self.number_of_contracts,
            'psar_mes': self.psar_mes,
            'psar_mym': self.psar_mym,
            'psar_difference': self.psar_difference,
            'simulated_mym': self.simulated_mym,
            'stop_loss_updates': self.stop_loss_updates
        }
        return {
            **ichimoku_dict,
            **super().to_dict()
        }