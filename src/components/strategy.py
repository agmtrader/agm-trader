from src.lib.params import BaseStrategyParams, IchimokuBaseParams
from abc import ABC, abstractmethod
from ib_insync import *
import numpy as np 
from src.utils.logger import logger

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

class IchimokuBase(Strategy):
    
    def __init__(self, initialParams: IchimokuBaseParams):
        super().__init__(initialParams)
        self.name = 'Ichimoku Base'
    
    def run(self):

        logger.info(f'Executing strategy...')

        # Calculate Tenkan and Kijun
        tenkan = self.calculate_tenkan(self.params.historicalData['MES'])
        kijun = self.calculate_kijun(self.params.historicalData['MES'])
        self.params.tenkan = tenkan
        self.params.kijun = kijun

        # Calculate current PSAR
        psar_mes = self.calculate_parabolic_sar(self.params.historicalData['MES'])
        psar_mym = self.calculate_parabolic_sar(self.params.historicalData['MYM'])
        self.params.psar_mes = psar_mes.tolist()
        self.params.psar_mym = psar_mym.tolist()

        # Extract current PSAR
        current_psar_mes = psar_mes[-1]
        current_psar_mym = psar_mym[-1]

        # Has it been 4 candles or less since the psar changed from negative to positive?
        trend_changed, candles_since_change = self.find_recent_trend_change(psar_mes, self.params.historicalData['MES'])
        
        # If yes, calculate highest high since that change
        highest_high = None
        if trend_changed:
            highest_high = self.calculate_highest_high_since_change(
                self.params.historicalData['MES'], 
                candles_since_change
            )

        # Get last PSAR of previous downtrend and first PSAR of current uptrend
        last_down_psar, first_up_psar = self.get_trend_change_psars(psar_mes, self.params.historicalData['MES'])
        
        # Buy signal
        if self.is_psar_negative(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_negative(current_psar_mym, self.params.historicalData['MYM']):
            self.params.number_of_contracts = 12
            logger.warning(f'Buy signal detected. Negative PSAR. 12 contracts')
            return 'BUY'
        elif self.is_psar_positive(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_positive(current_psar_mym, self.params.historicalData['MYM']) and candles_since_change <= 4:
            difference = abs(last_down_psar - first_up_psar)
            if highest_high < (difference * 0.618) and highest_high > (difference * 0.382):
                self.params.number_of_contracts = 6
                logger.warning(f'Buy signal detected. Positive PSAR. 6 contracts')
                return 'BUY'
            elif highest_high < (difference * 0.382):
                self.params.number_of_contracts = 12
                logger.warning(f'Buy signal detected. Positive PSAR. 12 contracts')
                return 'BUY'
        
        # Sellshort signal
        if self.is_psar_positive(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_negative(current_psar_mym, self.params.historicalData['MYM']) and kijun >= tenkan:
            self.params.number_of_contracts = 12
            logger.warning(f'Sellshort signal detected. Positive PSAR. 12 contracts')
            return 'SELLSHORT'
        elif self.is_psar_negative(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_positive(current_psar_mym, self.params.historicalData['MYM']) and kijun >= tenkan:
            self.params.number_of_contracts = 6
            logger.warning(f'Sellshort signal detected. Negative PSAR. 6 contracts')
            return 'SELLSHORT'
        
        # Take profit signal

        # Exit signal
        return 'STAY'
    
    def calculate_tenkan(self, data):
        last_5_days_mes = data[-5:]
        max_high_mes_5 = max(day['high'] for day in last_5_days_mes)
        min_low_mes_5 = min(day['low'] for day in last_5_days_mes)
        return 0.5 * (max_high_mes_5 + min_low_mes_5)
    
    def calculate_kijun(self, data):
        last_21_days_mes = data[-21:]
        max_high_mes_21 = max(day['high'] for day in last_21_days_mes)
        min_low_mes_21 = min(day['low'] for day in last_21_days_mes)
        return 0.5 * (max_high_mes_21 + min_low_mes_21)

    def calculate_parabolic_sar(self, data, start_af=0.02, increment_af=0.02, max_af=0.20):
        """
        Calculate Parabolic SAR indicator
        Parameters:
            high: array of high prices
            low: array of low prices
            close: array of closing prices
            start_af: starting acceleration factor (default 0.02)
            increment_af: acceleration factor increment (default 0.02)
            max_af: maximum acceleration factor (default 0.20)
        Returns:
            array of PSAR values
        """

        # Extract high, low, and close prices from the data
        high_prices = [day['high'] for day in data]
        low_prices = [day['low'] for day in data]
        close_prices = [day['close'] for day in data]
        
        # Convert inputs to numpy arrays if they aren't already
        high = np.array(high_prices)
        low = np.array(low_prices)
        close = np.array(close_prices)
        
        # Validate input data
        if len(high) == 0 or len(low) == 0 or len(close) == 0:
            return np.array([])
            
        # Initialize arrays and variables
        length = len(close)
        psar = np.zeros(length)
        bullish = True  # Start assuming uptrend
        af = start_af   # Acceleration factor
        ep = high[0]    # Extreme point
        
        # Set initial PSAR value (first value is just the low/high depending on trend)
        psar[0] = low[0]
        
        # Main calculation loop
        for i in range(1, length):
            # Carry over previous PSAR value
            psar[i] = psar[i-1]
            
            # Calculate PSAR for current period
            if bullish:
                psar[i] = psar[i-1] + af * (ep - psar[i-1])
                
                # Check if PSAR crosses below price
                if psar[i] > low[i]:
                    bullish = False
                    psar[i] = ep
                    af = start_af
                    ep = low[i]
                else:
                    # Update extreme point and acceleration factor
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + increment_af, max_af)
                    
                    # Ensure PSAR doesn't exceed yesterday's low
                    psar[i] = min(psar[i], low[i-1])
                    
            else:  # Bearish trend
                psar[i] = psar[i-1] + af * (ep - psar[i-1])
                
                # Check if PSAR crosses above price
                if psar[i] < high[i]:
                    bullish = True
                    psar[i] = ep
                    af = start_af
                    ep = high[i]
                else:
                    # Update extreme point and acceleration factor
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + increment_af, max_af)
                    
                    # Ensure PSAR doesn't exceed yesterday's high
                    psar[i] = max(psar[i], high[i-1])
        
        return psar

    def is_psar_positive(self, current_psar: float, data: list):
        if current_psar > data[-1]['close']:
            return True
        else:
            return False

    def is_psar_negative(self, current_psar: float, data: list):
        return not self.is_psar_positive(current_psar, data)

    def find_recent_trend_change(self, psar_data, historical_data, lookback=4):
        """Check if there was a trend change from negative to positive in last 4 candles"""
        if len(psar_data) < lookback + 1:
            return False, None
        
        # Look at the last few candles
        for i in range(1, lookback + 1):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            # Check if there was a change from negative to positive
            if (self.is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self.is_psar_positive(current_psar, [historical_data[-i]])):
                return True, i
        
        return False, None

    def calculate_highest_high_since_change(self, historical_data, candles_since_change):
        """Calculate the highest high since the trend changed"""
        relevant_data = historical_data[-candles_since_change:]
        return max(day['high'] for day in relevant_data)

    def get_trend_change_psars(self, psar_data, historical_data):
        """Get the last PSAR of previous downtrend and first PSAR of current uptrend"""
        for i in range(1, len(psar_data)):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            if (self.is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self.is_psar_positive(current_psar, [historical_data[-i]])):
                return prev_psar, current_psar
        
        return None, None

    def create_order(self, action: str):
        if action == 'BUY':
            return LimitOrder(
                symbol=self.params.contracts[0].symbol,
                quantity=self.params.number_of_contracts,
                action='BUY',
                limit_price=10000000
            )
        elif action == 'SELLSHORT':
            return LimitOrder(
                symbol=self.params.contracts[0].symbol,
                quantity=self.params.number_of_contracts,
                action='SELL',
                limit_price=10
            )
        else:
            return None
    
    def to_dict(self):
        return {
            'name': self.name,
            **super().to_dict()
        }