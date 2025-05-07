from src.lib.params import BaseStrategyParams, IchimokuBaseParams
from abc import ABC, abstractmethod
from ib_insync import *
import numpy as np 
from src.utils.logger import logger
from datetime import datetime

class Strategy(ABC):
    def __init__(self, initialParams: BaseStrategyParams):
        self.params = initialParams
    
    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def create_order(self, action: str):
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

        # Calculate highest high and lowest low since the trend change
        highest_high = None
        lowest_low = None
        if trend_changed and candles_since_change is not None:

            # Get last psar of previous downtrend and first psar of current uptrend
            last_down_psar, first_up_psar = self.get_trend_change_psars(psar_mes, self.params.historicalData['MES'])

            highest_high = self.calculate_highest_high_since_change(self.params.historicalData['MES'], candles_since_change)
            lowest_low = self.calculate_lowest_low_since_change(self.params.historicalData['MES'], candles_since_change)
        
        """
        BUY SIGNALS:

        1. If PSAR MES is negative and PSAR MYM is negative, put a limit buy order at the PSAR MES price
        (to take the trend change). Open 12 contracts in this occasion.

        2. If the current candle is between the 4 first candles of the positive trend started by the PSAR,
        and if PSAR MES + and PSAR MYM + and the highest high since the positive trend started by the PSAR
        is less than 61.8% of the difference between the last PSAR of the previous downtrend and the first PSAR of the current uptrend,
        we buy the following number of contracts:
        - If close of the candle where this happens is less than 38.2% of said difference,
        we buy 12 contracts
        - If close of the candle where this happens is greater than 38.2% of said difference,
        we buy 6 contracts only (because we will have already exceeded the Take Profit 1)
        """

        if self.is_psar_negative(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_negative(current_psar_mym, self.params.historicalData['MYM']):
            self.params.number_of_contracts = 12
            logger.warning(f'Buy signal detected. Negative PSAR. 12 contracts')
            return 'BUY'
        elif self.is_psar_positive(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_positive(current_psar_mym, self.params.historicalData['MYM']) and trend_changed and candles_since_change is not None and candles_since_change <= 4:
            difference = abs(last_down_psar - first_up_psar)
            if highest_high < (difference * 0.618):
                if highest_high < (difference * 0.382):
                    self.params.number_of_contracts = 12
                else:
                    self.params.number_of_contracts = 6
                logger.warning(f'Buy signal detected. Positive PSAR. 6 contracts')
                return 'BUY'
            
        """
        SELLSHORT SIGNALS:

        1. If PSAR MES + and PSAR MYM +, and Kijun >= Tenkan, put a limit sell order at the PSAR MES price
        (to take the trend change). Open 12 contracts in this occasion.

        2. If the current candle is between the 4 first candles of the negative trend started by the PSAR,
        and if PSAR MES - and PSAR MYM - and the lowest low since the negative trend started by the PSAR
        is greater than 61.8% of the difference between the last PSAR of the previous downtrend and the first PSAR of the current uptrend,
        we sell the following number of contracts:
        - If close of the candle where this happens is greater than 38.2% of said difference,
        we sell 12 contracts
        - If close of the candle where this happens is less than 38.2% of said difference,
        we sell 6 contracts only (because we will have already exceeded the Take Profit 1)
        """

        if self.is_psar_positive(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_negative(current_psar_mym, self.params.historicalData['MYM']) and kijun >= tenkan:
            self.params.number_of_contracts = 12
            logger.warning(f'Sellshort signal detected. Positive PSAR. 12 contracts')
            return 'SELLSHORT'
        elif self.is_psar_negative(current_psar_mes, self.params.historicalData['MES']) and self.is_psar_positive(current_psar_mym, self.params.historicalData['MYM']) and kijun >= tenkan:
            difference = abs(last_down_psar - first_up_psar)
            if lowest_low > (difference * 0.618):
                if lowest_low > (difference * 0.382):
                    self.params.number_of_contracts = 6
                else:
                    self.params.number_of_contracts = 12
                logger.warning(f'Sellshort signal detected. Negative PSAR. 6 contracts')
                return 'SELLSHORT'

        """
        EXIT SIGNALS:
        1. If the weekly candle of MES is red (close < open), exit the long position
        2. If the weekly candle of MES is green (close > open), exit the short position
        3. If we have entered with a limit order and the closing of that first entry candle is
        opposite to the operation, we close. That is, if we are LONG and the closing of the entry
        candle is red (close < open), we close. If we are SHORT and the closing of the entry
        candle is green (close > open), we close.
        4. If we have entered with a limit order and at the closing of that entry candle the PSAR
        of MYM is not aligned with the PSAR of MES, we close. That is, if we have entered
        LONG with a limit order and at the closing of that entry candle the PSAR of MYM still
        SHORT, we close. And vice versa.
        """
        is_weekly_candle, current_candle, prev_candle = self.get_weekly_candle(self.params.historicalData['MES'])
        
        if is_weekly_candle:
            # If the weekly candle is red (close < open), exit the long position
            if current_candle['close'] < current_candle['open']:
                logger.warning(f'Weekly exit signal detected. Red weekly candle - exit long position.')
                return 'EXITLONG'
            # If the weekly candle is green (close > open), exit the short position
            elif current_candle['close'] > current_candle['open']:
                logger.warning(f'Weekly exit signal detected. Green weekly candle - exit short position.')
                return 'EXITSHORT'
            
        
        return 'STAY'
    
    def create_order(self, action: str):

        current_price = self.params.historicalData['MES'][-1]['close']


        if action == 'BUY':

            limit_order = LimitOrder(
                totalQuantity=self.params.number_of_contracts,
                action='BUY',
                lmtPrice=self.params.psar_mes[-1]
            )

            stop_loss = StopOrder(
                totalQuantity=self.params.number_of_contracts,
                action='SELL',
                stopPrice=self.params.psar_mes[-1]
            )

            # Exit contracts 1-6: on 38.2% of the difference between the jump between the last PSAR of the previous downtrend and the first PSAR of the current uptrend.
            # Exit contracts 7-12: on 61.8% of the difference between the jump between the last PSAR of the previous downtrend and the first PSAR of the current uptrend.
            take_profit = LimitOrder(
                totalQuantity=self.params.number_of_contracts,
                action='SELL',
                lmtPrice=current_price
            )

            order = BracketOrder(
                parent=limit_order,
                takeProfit=take_profit,
                stopLoss=stop_loss
            )
            return order
        
        elif action == 'SELLSHORT':

            limit_order = LimitOrder(
                totalQuantity=self.params.number_of_contracts,
                action='SELL',
                lmtPrice=self.params.psar_mes[-1]
            )

            stop_loss = StopOrder(
                totalQuantity=self.params.number_of_contracts,
                action='BUY',
                stopPrice=self.params.psar_mes[-1]
            )

            take_profit = LimitOrder(
                totalQuantity=self.params.number_of_contracts,
                action='BUY',
                lmtPrice=current_price
            )

            order = BracketOrder(
                parent=limit_order,
                takeProfit=take_profit,
                stopLoss=stop_loss
            )
            return order
        
        else:
            return None

    def to_dict(self):
        return {
            'name': self.name,
            **super().to_dict()
        }

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
            return False, lookback + 1
        
        # Look at the last few candles
        for i in range(1, lookback + 1):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            # Check if there was a change from negative to positive
            if (self.is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self.is_psar_positive(current_psar, [historical_data[-i]])):
                return True, i
        
        return False, lookback + 1  # Return a value larger than lookback to indicate no recent change

    def calculate_highest_high_since_change(self, historical_data, candles_since_change):
        """Calculate the highest high since the trend changed"""
        relevant_data = historical_data[-candles_since_change:]
        return max(day['high'] for day in relevant_data)
    
    def calculate_lowest_low_since_change(self, historical_data, candles_since_change):
        """Calculate the lowest low since the trend changed"""
        relevant_data = historical_data[-candles_since_change:]
        return min(day['low'] for day in relevant_data)

    def get_trend_change_psars(self, psar_data, historical_data):
        """Get the last PSAR of previous downtrend and first PSAR of current uptrend"""
        for i in range(1, len(psar_data)):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            if (self.is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self.is_psar_positive(current_psar, [historical_data[-i]])):
                return prev_psar, current_psar
        
        return None, None

    def get_weekly_candle(self, data):
        """
        Get the weekly candle data if the current candle is the last one of the week (Friday)
        Returns:
            tuple: (is_weekly_candle, current_candle, prev_candle) where is_weekly_candle is a boolean
        """
        if len(data) < 2:
            return False, None, None
            
        current_candle = data[-1]
        prev_candle = data[-2]
        
        # Get the date from the candle data
        current_date = current_candle.get('date')
        prev_date = prev_candle.get('date')
        
        if not (current_date and prev_date):
            return False, None, None
            
        # Convert string dates to datetime objects if needed
        if isinstance(current_date, str):
            current_date = datetime.strptime(current_date, '%Y-%m-%d')
        if isinstance(prev_date, str):
            prev_date = datetime.strptime(prev_date, '%Y-%m-%d')
        
        # Check if current candle is Friday and previous candle is from a different week
        is_weekly_candle = (current_date.weekday() == 4 and  # Friday
                          current_date.isocalendar()[1] != prev_date.isocalendar()[1])  # Different week
        
        return is_weekly_candle, current_candle, prev_candle
    
    def calculate_number_of_contracts(self, take_profit, stop_loss):
        return 12
