from ib_insync import *
from typing import List, Dict, Any, Optional
import datetime

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
