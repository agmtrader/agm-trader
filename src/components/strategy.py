from src.lib.params import BaseStrategyParams, IchimokuBaseParams, ContractData
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
        logger.announcement(f'Executing strategy...', 'info')

        # Get contract data
        mes_data = self.params.get_mes_data()
        mym_data = self.params.get_mym_data()
        
        if not mes_data or not mym_data:
            logger.error("MES or MYM contract data not found")
            return 'STAY'
            
        if not mes_data.has_data() or not mym_data.has_data():
            logger.error("Historical data not available for MES or MYM")
            return 'STAY'

        logger.info(f"MES data points: {len(mes_data.data)}, MYM data points: {len(mym_data.data)}")
        
        # Check if we have valid price data
        mes_price = mes_data.get_latest_price()
        mym_price = mym_data.get_latest_price()
        
        if mes_price is None or mym_price is None:
            logger.error("Latest price data is missing")
            return 'STAY'
            
        logger.info(f"Latest MES price: {mes_price:.2f}, Latest MYM price: {mym_price:.2f}")

        # Calculate Tenkan and Kijun
        tenkan = self.calculate_tenkan(mes_data.data)
        kijun = self.calculate_kijun(mes_data.data)
        self.params.tenkan = tenkan
        self.params.kijun = kijun
        logger.info(f"Tenkan: {tenkan:.2f}, Kijun: {kijun:.2f}")

        # Calculate current PSAR
        try:
            psar_mes = self.calculate_parabolic_sar(mes_data.data)
            psar_mym = self.calculate_parabolic_sar(mym_data.data)
            
            if len(psar_mes) == 0 or len(psar_mym) == 0:
                logger.error("PSAR calculation returned empty arrays")
                return 'STAY'
                
            self.params.psar_mes = psar_mes.tolist()
            self.params.psar_mym = psar_mym.tolist()

            # Extract current PSAR
            current_psar_mes = psar_mes[-1]
            current_psar_mym = psar_mym[-1]
            logger.info(f"Current PSAR MES: {current_psar_mes:.2f}, Current PSAR MYM: {current_psar_mym:.2f}")
        except Exception as e:
            logger.error(f"Error calculating PSAR: {str(e)}")
            return 'STAY'

        # Has it been 4 candles or less since the psar changed from negative to positive?
        trend_changed, candles_since_change = self.find_recent_trend_change(psar_mes, mes_data.data)
        logger.info(f"Trend changed: {trend_changed}, Candles since change: {candles_since_change}")

        # Calculate highest high and lowest low since the trend change
        highest_high = None
        lowest_low = None
        last_down_psar = None
        first_up_psar = None
        difference = 0
        
        if trend_changed and candles_since_change is not None:
            # Get last psar of previous downtrend and first psar of current uptrend
            last_down_psar, first_up_psar = self.get_trend_change_psars(psar_mes, mes_data.data)

            # Calculate difference properly with null checks
            if last_down_psar is not None and first_up_psar is not None:
                difference = abs(last_down_psar - first_up_psar)
            else:
                difference = 0

            highest_high = self.calculate_highest_high_since_change(mes_data.data, candles_since_change)
            lowest_low = self.calculate_lowest_low_since_change(mes_data.data, candles_since_change)
            logger.info(f"Highest high since change: {highest_high}, Lowest low since change: {lowest_low}")
            logger.info(f"Last down PSAR: {last_down_psar}, First up PSAR: {first_up_psar}")
            logger.info(f"PSAR difference: {difference:.2f}")
        
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

        # Check PSAR conditions
        mes_psar_negative = self.is_psar_negative(current_psar_mes, mes_data.data)
        mym_psar_negative = self.is_psar_negative(current_psar_mym, mym_data.data)
        mes_psar_positive = self.is_psar_positive(current_psar_mes, mes_data.data)
        mym_psar_positive = self.is_psar_positive(current_psar_mym, mym_data.data)
        
        logger.info(f"MES PSAR negative: {mes_psar_negative}, MYM PSAR negative: {mym_psar_negative}")
        logger.info(f"MES PSAR positive: {mes_psar_positive}, MYM PSAR positive: {mym_psar_positive}")

        if mes_psar_negative and mym_psar_negative:
            self.params.number_of_contracts = 12
            self.params.psar_difference = 0  # Store for later use in order creation
            logger.warning(f'Buy signal detected. Negative PSAR. 12 contracts')
            return 'LONG'
        elif mes_psar_positive and mym_psar_positive and trend_changed and candles_since_change is not None and candles_since_change <= 4:
            if difference > 0 and highest_high and highest_high < (difference * 0.618):
                # Get the entry candle (the one from candles_since_change ago)
                entry_candle = mes_data.data[-candles_since_change]
                entry_close = entry_candle['close']
                
                # Compare entry candle close to thresholds, not highest_high
                if entry_close < (difference * 0.382):
                    self.params.number_of_contracts = 12
                    logger.warning(f'Buy signal detected. Positive PSAR. 12 contracts (entry close < 38.2%)')
                else:
                    self.params.number_of_contracts = 6
                    logger.warning(f'Buy signal detected. Positive PSAR. 6 contracts (entry close >= 38.2%)')
                
                self.params.psar_difference = difference  # Store for later use in order creation
                return 'LONG'
            
        """
        SELLSHORT SIGNALS:

        1. If PSAR MES + and PSAR MYM +, and Kijun >= Tenkan, put a limit sell order at the PSAR MES price
        (to take the trend change). Open 12 contracts in this occasion.

        2. If the current candle is between the 4 first candles of the negative trend started by the PSAR,
        and if PSAR MES - and PSAR MYM -, and Kijun >= Tenkan, and the lowest low since the negative trend started by the PSAR
        is greater than 61.8% of the difference between the last PSAR of the previous uptrend and the first PSAR of the current downtrend,
        we sell the following number of contracts:
        - If close of the candle where this happens is greater than 38.2% of said difference,
        we sell 4 contracts
        - If close of the candle where this happens is less than 38.2% of said difference,
        we sell 2 contracts only (because we will have already exceeded the Take Profit 1)
        """

        # Check for negative trend change (down to up) for SHORT scale-in conditions
        down_trend_changed, down_candles_since_change = self.find_recent_downtrend_change(psar_mes, mes_data.data)
        
        if mes_psar_positive and mym_psar_positive and kijun >= tenkan:
            self.params.number_of_contracts = 12
            self.params.psar_difference = 0  # Store for later use in order creation
            logger.warning(f'Sellshort signal detected. MES+ MYM+ Kijun>=Tenkan. 12 contracts')
            return 'SHORT'
        elif (mes_psar_negative and mym_psar_negative and kijun >= tenkan and 
              down_trend_changed and down_candles_since_change is not None and down_candles_since_change <= 4):
            if difference > 0 and lowest_low and lowest_low > (difference * 0.618):
                # Get the entry candle (the one from down_candles_since_change ago)
                entry_candle = mes_data.data[-down_candles_since_change]
                entry_close = entry_candle['close']
                
                # Compare entry candle close to thresholds (per specification)
                if entry_close > (difference * 0.382):
                    # Above 38.2% => 4 contracts (per specification)
                    self.params.number_of_contracts = 4
                    logger.warning(f'Sellshort signal detected. 4 contracts (entry close > 38.2%)')
                else:
                    # Below 38.2% => 2 contracts (per specification - already cleared TP1)
                    self.params.number_of_contracts = 2
                    logger.warning(f'Sellshort signal detected. 2 contracts (entry close <= 38.2%)')
                
                self.params.psar_difference = difference  # Store for later use in order creation
                return 'SHORT'

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
        # Check weekly candle exit conditions
        is_weekly_candle, current_candle, prev_candle = self.get_weekly_candle(mes_data.data)
        logger.info(f"Is weekly candle: {is_weekly_candle}")
        
        if is_weekly_candle and current_candle:
            logger.info(f"Weekly candle - Open: {current_candle['open']:.2f}, Close: {current_candle['close']:.2f}")
            # If the weekly candle is red (close < open), exit the long position
            if current_candle['close'] < current_candle['open']:
                logger.warning(f'Weekly exit signal detected. Red weekly candle - exit long position.')
                return 'EXIT'
            # If the weekly candle is green (close > open), exit the short position
            elif current_candle['close'] > current_candle['open']:
                logger.warning(f'Weekly exit signal detected. Green weekly candle - exit short position.')
                return 'EXIT'

        # Check MYM simulation for early exits
        mym_exit_signal = self._check_mym_simulation()
        if mym_exit_signal != 'STAY':
            logger.warning(f'MYM simulation exit signal: {mym_exit_signal}')
            return 'EXIT'

        # Check entry candle validation (if we have existing positions)
        entry_candle_exit = self._check_entry_candle_validation(mes_data.data, mym_data.data, current_psar_mes, current_psar_mym)
        if entry_candle_exit:
            logger.warning('Entry candle validation failed - triggering exit')
            return 'EXIT'

        # Update stop losses with current PSAR levels if we have open positions
        stop_loss_updates = self._update_stop_losses(current_psar_mes, current_psar_mym)
            
        logger.info("No signals detected - staying in current position")
        return 'STAY'
    
    def create_order(self, action: str):
        mes_data = self.params.get_mes_data()
        mym_data = self.params.get_mym_data()
        
        if not mes_data or not mes_data.has_data():
            logger.error("No MES data available for order creation")
            return None
        
        if not mym_data or not mym_data.has_data():
            logger.error("No MYM data available for order creation")
            return None

        # Get entry prices from PSAR
        mes_psar_price = self.params.psar_mes[-1] if self.params.psar_mes else mes_data.get_latest_price()
        mym_psar_price = self.params.psar_mym[-1] if self.params.psar_mym else mym_data.get_latest_price()
        
        # Get the PSAR difference for calculating TP levels
        difference = getattr(self.params, 'psar_difference', 0)
        
        qty = self.params.number_of_contracts
        
        # Calculate TP quantities based on position type and contract count
        if action == 'LONG':
            # For LONG: max 12 contracts, TP1 = first 6, TP2 = remaining 6
            tp1_qty = min(6, qty // 2) if qty <= 12 else 6
            tp2_qty = qty - tp1_qty
        else:  # SHORT
            # For SHORT: max 4 contracts, TP1 = first 2, TP2 = remaining 2
            tp1_qty = min(2, qty // 2) if qty <= 4 else 2
            tp2_qty = qty - tp1_qty

        logger.info(f"Creating {action} order with {qty} contracts")
        logger.info(f"MES entry price: {mes_psar_price:.2f}, MYM entry price: {mym_psar_price:.2f}")
        logger.info(f"PSAR difference: {difference:.2f}")

        if action == 'LONG':
            # Calculate levels
            entry_price = mes_psar_price
            sl_price = mes_psar_price  # Stop at PSAR level
            
            if difference > 0:
                tp1_price = entry_price + (difference * 0.382)
                tp2_price = entry_price + (difference * 0.618)
            else:
                # Fallback for immediate PSAR entries - use a reasonable percentage
                tp1_price = entry_price * 1.002  # 0.2% profit
                tp2_price = entry_price * 1.005  # 0.5% profit
            
            logger.info(f"LONG levels - Entry: {entry_price:.2f}, SL: {sl_price:.2f}, TP1: {tp1_price:.2f}, TP2: {tp2_price:.2f}")

            # Create parent entry order
            parent = LimitOrder(
                totalQuantity=qty,
                action='BUY',
                lmtPrice=entry_price,
                transmit=False
            )

            # Create stop loss for full quantity
            stop_loss = StopOrder(
                totalQuantity=qty,
                action='SELL',
                stopPrice=sl_price,
                parentId=parent.orderId,
                transmit=False
            )

            # Create take profit orders
            tp1 = LimitOrder(
                totalQuantity=tp1_qty,
                action='SELL',
                lmtPrice=tp1_price,
                parentId=parent.orderId,
                transmit=False
            )

            tp2 = LimitOrder(
                totalQuantity=tp2_qty,
                action='SELL',
                lmtPrice=tp2_price,
                parentId=parent.orderId,
                transmit=True  # Last order transmits all
            )

            # Store MYM simulation data
            self._setup_mym_simulation('LONG', mym_psar_price, tp1_price, tp2_price, sl_price, qty)
            
            return [parent, stop_loss, tp1, tp2]
        
        elif action == 'SHORT':
            # Calculate levels
            entry_price = mes_psar_price
            sl_price = mes_psar_price  # Stop at PSAR level (this will be updated daily)
            
            if difference > 0:
                tp1_price = entry_price - (difference * 0.382)
                tp2_price = entry_price - (difference * 0.618)
            else:
                # Fallback for immediate PSAR entries
                tp1_price = entry_price * 0.998  # 0.2% profit
                tp2_price = entry_price * 0.995  # 0.5% profit
            
            logger.info(f"SHORT levels - Entry: {entry_price:.2f}, SL: {sl_price:.2f}, TP1: {tp1_price:.2f}, TP2: {tp2_price:.2f}")

            # Create parent entry order
            parent = LimitOrder(
                totalQuantity=qty,
                action='SELL',
                lmtPrice=entry_price,
                transmit=False
            )

            # Create stop loss for full quantity (for SHORT, SL should be above entry price)
            stop_loss = StopOrder(
                totalQuantity=qty,
                action='BUY',
                stopPrice=sl_price,
                parentId=parent.orderId,
                transmit=False
            )

            # Create take profit orders
            tp1 = LimitOrder(
                totalQuantity=tp1_qty,
                action='BUY',
                lmtPrice=tp1_price,
                parentId=parent.orderId,
                transmit=False
            )

            tp2 = LimitOrder(
                totalQuantity=tp2_qty,
                action='BUY',
                lmtPrice=tp2_price,
                parentId=parent.orderId,
                transmit=True  # Last order transmits all
            )

            # Store MYM simulation data
            self._setup_mym_simulation('SHORT', mym_psar_price, tp1_price, tp2_price, sl_price, qty)
            
            return [parent, stop_loss, tp1, tp2]
        
        else:
            logger.info(f"No order created for action: {action}")
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
        # PSAR is positive when it's above the price (per specification)
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

    def find_recent_downtrend_change(self, psar_data, historical_data, lookback=4):
        """Check if there was a trend change from positive to negative in last 4 candles"""
        if len(psar_data) < lookback + 1:
            return False, lookback + 1
        
        # Look at the last few candles
        for i in range(1, lookback + 1):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            # Check if there was a change from positive to negative
            if (self.is_psar_positive(prev_psar, [historical_data[-(i+1)]]) and 
                self.is_psar_negative(current_psar, [historical_data[-i]])):
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
    
    def _setup_mym_simulation(self, action, entry_price, tp1_price, tp2_price, sl_price, qty):
        """Set up MYM simulation to monitor for early exits"""
        if not hasattr(self.params, 'simulated_mym'):
            self.params.simulated_mym = []
        
        simulation = {
            'action': action,
            'entry': entry_price,
            'tp1': tp1_price,
            'tp2': tp2_price,
            'sl': sl_price,
            'qty': qty,
            'tp1_hit': False,
            'tp2_hit': False,
            'sl_hit': False
        }
        
        self.params.simulated_mym.append(simulation)
        logger.info(f"MYM simulation setup - Action: {action}, Entry: {entry_price:.2f}, TP1: {tp1_price:.2f}, TP2: {tp2_price:.2f}, SL: {sl_price:.2f}")

    def _check_mym_simulation(self):
        """Check if any MYM simulated positions should trigger exits"""
        if not hasattr(self.params, 'simulated_mym') or not self.params.simulated_mym:
            return 'STAY'
        
        mym_data = self.params.get_mym_data()
        if not mym_data or not mym_data.has_data():
            return 'STAY'
        
        current_mym_price = mym_data.get_latest_price()
        logger.info(f"Checking MYM simulation against current price: {current_mym_price:.2f}")
        
        for i, sim in enumerate(self.params.simulated_mym):
            if sim['action'] == 'LONG':
                # Check TP levels
                if not sim['tp1_hit'] and current_mym_price >= sim['tp1']:
                    logger.warning(f"MYM simulation TP1 hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['tp1_hit'] = True
                    return 'EXIT_MYM_TP1'
                elif not sim['tp2_hit'] and current_mym_price >= sim['tp2']:
                    logger.warning(f"MYM simulation TP2 hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['tp2_hit'] = True
                    return 'EXIT_MYM_TP2'
                # Check SL
                elif not sim['sl_hit'] and current_mym_price <= sim['sl']:
                    logger.warning(f"MYM simulation SL hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['sl_hit'] = True
                    return 'EXIT_MYM_SL'
            
            elif sim['action'] == 'SHORT':
                # Check TP levels
                if not sim['tp1_hit'] and current_mym_price <= sim['tp1']:
                    logger.warning(f"MYM simulation TP1 hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['tp1_hit'] = True
                    return 'EXIT_MYM_TP1'
                elif not sim['tp2_hit'] and current_mym_price <= sim['tp2']:
                    logger.warning(f"MYM simulation TP2 hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['tp2_hit'] = True
                    return 'EXIT_MYM_TP2'
                # Check SL
                elif not sim['sl_hit'] and current_mym_price >= sim['sl']:
                    logger.warning(f"MYM simulation SL hit at {current_mym_price:.2f} - triggering MES exit")
                    sim['sl_hit'] = True
                    return 'EXIT_MYM_SL'
        
        return 'STAY'

    def _clear_mym_simulation(self):
        """Clear MYM simulation data"""
        if hasattr(self.params, 'simulated_mym'):
            self.params.simulated_mym.clear()
            logger.info("MYM simulation data cleared")

    def calculate_number_of_contracts(self, take_profit, stop_loss):
        return 12

    def _check_entry_candle_validation(self, mes_data, mym_data, psar_mes, psar_mym):
        """
        Check entry candle validation exit conditions:
        1. If entry candle close is opposite to operation (LONG with red candle, SHORT with green candle)
        2. If PSAR MYM is not aligned with PSAR MES at entry candle close
        """
        # Check if we have any open positions
        if not self.params.positions:
            return False
            
        # Get current positions
        for position in self.params.positions:
            if abs(position['position']) > 0:  # We have an open position
                # Check if this is the entry candle (just entered)
                if len(self.params.executed_orders) > 0:
                    # Get the most recent executed order
                    last_executed = self.params.executed_orders[-1]
                    
                    # Check if order was executed on current candle
                    if last_executed.get('isActive', False) == False and last_executed.get('isDone', False) == True:
                        current_candle = mes_data[-1]
                        
                        # Check if it's a LONG position
                        if position['position'] > 0:
                            # For LONG position, exit if current candle is red (close < open)
                            if current_candle['close'] < current_candle['open']:
                                logger.warning(f"Entry candle validation: LONG position with red candle - exit")
                                return True
                            
                            # Check PSAR alignment - MYM should also be positive for LONG
                            if self.is_psar_negative(psar_mym, [mym_data[-1]]):
                                logger.warning(f"Entry candle validation: LONG position but MYM PSAR is negative - exit")
                                return True
                        
                        # Check if it's a SHORT position
                        elif position['position'] < 0:
                            # For SHORT position, exit if current candle is green (close > open)
                            if current_candle['close'] > current_candle['open']:
                                logger.warning(f"Entry candle validation: SHORT position with green candle - exit")
                                return True
                            
                            # Check PSAR alignment - MYM should also be negative for SHORT
                            if self.is_psar_positive(psar_mym, [mym_data[-1]]):
                                logger.warning(f"Entry candle validation: SHORT position but MYM PSAR is positive - exit")
                                return True
        
        return False

    def _update_stop_losses(self, psar_mes, psar_mym):
        """
        Update stop loss levels with current PSAR levels if we have open positions
        Returns a list of stop loss updates that need to be applied to broker orders
        """
        stop_loss_updates = []
        
        # Check if we have any open positions
        if not self.params.positions:
            return stop_loss_updates
            
        # Get current positions
        for position in self.params.positions:
            if abs(position['position']) > 0:  # We have an open position
                contract_symbol = position['contract']['symbol']
                
                # Check if this is a LONG position
                if position['position'] > 0:
                    new_sl = psar_mes
                    logger.info(f"LONG position in {contract_symbol}: updating SL to PSAR MES {new_sl:.2f}")
                    stop_loss_updates.append({
                        'symbol': contract_symbol,
                        'position_type': 'LONG',
                        'new_sl': new_sl,
                        'quantity': position['position']
                    })
                    
                # Check if this is a SHORT position
                elif position['position'] < 0:
                    new_sl = psar_mes  # For SHORT, SL is also based on MES PSAR
                    logger.info(f"SHORT position in {contract_symbol}: updating SL to PSAR MES {new_sl:.2f}")
                    stop_loss_updates.append({
                        'symbol': contract_symbol,
                        'position_type': 'SHORT',
                        'new_sl': new_sl,
                        'quantity': abs(position['position'])
                    })
        
        # Store the updates in params so trader can access them
        self.params.stop_loss_updates = stop_loss_updates
        return stop_loss_updates
