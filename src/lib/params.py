from abc import ABC
from src.lib.contract_data import ContractData
from ib_insync import *
from typing import List, Dict, Any, Optional


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
