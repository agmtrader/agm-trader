from abc import ABC, abstractmethod
from src.lib.params import BaseStrategyParams
from src.lib.params import BaseStrategyParams, IchimokuBaseParams, SMACrossoverParams
from abc import ABC, abstractmethod
from ib_insync import *
import numpy as np 
from src.utils.logger import logger
from datetime import datetime
from src.lib.backtest import TradeSnapshot
import pandas as pd

class Strategy(ABC):
    def __init__(self, initialParams: BaseStrategyParams):
        self.params = initialParams
        self.timeframe = '1 day'
        self.timeframe_seconds = 86400
    
    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def create_orders(self, action: str):
        pass

    @abstractmethod
    def refresh_params(self, data_manager):
        """Refresh internal parameters using the supplied DataManager instance."""
        pass

    @abstractmethod
    def backtest(self):
        pass

    def to_dict(self):
        return {
            'params': self.params.to_dict()
        }

    def has_open_position(self):
        """Return True if any open position is currently held (long or short)."""
        for pos in getattr(self.params, 'positions', []):
            if abs(pos.get('position', 0)) > 0:
                return True
        return False

class IchimokuBase(Strategy):
    
    def __init__(self, initialParams: IchimokuBaseParams):
        super().__init__(initialParams)
        self.name = 'Ichimoku Base'    

    def to_dict(self):
        return {
            'name': self.name,
            **super().to_dict()
        }

    def refresh_params(self, data_manager):
        logger.announcement("Refreshing strategy params...", 'info')
        for contract_data in self.params.contracts:
            contract_data.data = data_manager.get_historical_data(contract_data.contract, bar_size=self.timeframe)
        self.params.open_orders = data_manager.get_open_orders()
        self.params.executed_orders = data_manager.get_completed_orders()
        self.params.positions = data_manager.get_positions()
        logger.success("Successfully refreshed strategy params.")

    def run(self):
        """Execute the Ichimoku-Base strategy decision engine.

        The logic is a Python translation of the TradingView Pine-script shared by the
        user.  Each call analyses the **latest** candle of the MES contract (primary)
        and, where required, information from the MYM contract (secondary) to decide
        whether to go **LONG**, **SHORT**, **EXIT** or **STAY**.

        Notes
        -----
        1. This method is intentionally *stateless* – every invocation recomputes the
           required indicators from scratch based on the historical data currently
           loaded in ``self.params``.  This avoids the complexity of persisting
           auxiliary variables (bars_since_flip, first_psar, …) between calls while
           still replicating the behaviour of the Pine-script, which also looks back
           only a few candles (≤4).
        2. All helper methods used here are already implemented in this class:
           `_calculate_parabolic_sar`, `_calculate_tenkan`, `_calculate_kijun`,
           `_find_recent_trend_change`, `_find_recent_downtrend_change`, …
        """

        # Convenience aliases ────────────────────────────────────────────────────
        mes_contract = self.params.get_mes_data()
        mym_contract = self.params.get_mym_data()

        if not (mes_contract and mym_contract):
            logger.error("Missing MES or MYM contract data – staying idle")
            return "STAY"

        mes_data = mes_contract.data
        mym_data = mym_contract.data

        # We need at least 22 candles for Kijun (21-period high/low) + current
        min_len_required = 22
        if len(mes_data) < min_len_required or len(mym_data) < min_len_required:
            logger.warning("Not enough historical data – waiting …")
            return "STAY"

        # ----------------------------------------------------------------------
        # 1. Indicator calculation (PSAR, Tenkan, Kijun)                       |
        # ----------------------------------------------------------------------

        psar_mes_series = self._calculate_parabolic_sar(mes_data)
        psar_mym_series = self._calculate_parabolic_sar(mym_data)

        if len(psar_mes_series) == 0 or len(psar_mym_series) == 0:
            logger.error("Could not compute PSAR – staying idle")
            return "STAY"

        # Persist indicators so that create_orders() can reuse them -------------
        mes_contract.indicators["psar"] = psar_mes_series.tolist()
        mym_contract.indicators["psar"] = psar_mym_series.tolist()

        tenkan = self._calculate_tenkan(mes_data)
        kijun = self._calculate_kijun(mes_data)

        # Save to params so outside world (UI, debugging) can access ------------
        self.params.indicators['tenkan'] = tenkan
        self.params.indicators['kijun'] = kijun

        # ----------------------------------------------------------------------
        # 2. Define trend / flip variables just like the Pine-script             |
        # ----------------------------------------------------------------------

        close_mes = mes_data[-1]["close"]
        open_mes = mes_data[-1]["open"]
        close_mym = mym_data[-1]["close"]
        open_mym = mym_data[-1]["open"]

        psar_mes = psar_mes_series[-1]
        psar_mes_prev = psar_mes_series[-2] if len(psar_mes_series) >= 2 else psar_mes

        psar_mym = psar_mym_series[-1]
        psar_mym_prev = psar_mym_series[-2] if len(psar_mym_series) >= 2 else psar_mym

        trend_up_mes = psar_mes < close_mes
        trend_down_mes = psar_mes > close_mes
        trend_up_mym = psar_mym < close_mym
        trend_down_mym = psar_mym > close_mym

        flip_up_mes = trend_up_mes and not (psar_mes_prev < mes_data[-2]["close"])
        flip_down_mes = trend_down_mes and not (psar_mes_prev > mes_data[-2]["close"])

        flip_up_mym = trend_up_mym and not (psar_mym_prev < mym_data[-2]["close"])
        flip_down_mym = trend_down_mym and not (psar_mym_prev > mym_data[-2]["close"])

        # ----------------------------------------------------------------------
        # 3. Bars since flip & PSAR diff calculations (MES)                     |
        # ----------------------------------------------------------------------

        # Determine if an up-trend or down-trend flip occurred within last 4 bars
        change_up, candles_since_up = self._find_recent_trend_change(
            psar_mes_series, mes_data, lookback=4
        )
        change_down, candles_since_down = self._find_recent_downtrend_change(
            psar_mes_series, mes_data, lookback=4
        )

        # We only need bars_since_flip when there *was* a change recently.
        bars_since_flip_mes = candles_since_up if change_up else (
            candles_since_down if change_down else 999
        )

        # Get last PSAR of previous trend and first of current trend for diff ---
        prev_psar, first_psar = self._get_trend_change_psars(psar_mes_series, mes_data)
        diff_mes = abs(prev_psar - first_psar) if (prev_psar and first_psar) else 0

        # Keep difference available for order sizing/pricing --------------------
        self.params.psar_difference = diff_mes

        # ----------------------------------------------------------------------
        # 4. Recreate the Pine-script entry logic                                |
        # ----------------------------------------------------------------------

        # Initial entries -------------------------------------------------------
        buy_initial = (
            flip_up_mes and trend_up_mym and (close_mes > open_mes) and not self.has_open_position()
        )

        sell_initial = (
            flip_down_mes
            and trend_down_mym
            and (kijun >= tenkan)
            and (close_mes < open_mes)
            and not self.has_open_position()
        )

        # Re-entries ------------------------------------------------------------
        max_high_since_flip = self._calculate_highest_high_since_change(
            mes_data, bars_since_flip_mes
        ) if bars_since_flip_mes <= len(mes_data) else 0

        min_low_since_flip = self._calculate_lowest_low_since_change(
            mes_data, bars_since_flip_mes
        ) if bars_since_flip_mes <= len(mes_data) else 0

        buy_reentry = (
            2 <= bars_since_flip_mes <= 4
            and trend_up_mes
            and trend_up_mym
            and (max_high_since_flip < first_psar + 0.618 * diff_mes)
            and (close_mes > open_mes)
            and not self.has_open_position()
        )

        sell_reentry = (
            2 <= bars_since_flip_mes <= 4
            and trend_down_mes
            and trend_down_mym
            and (kijun >= tenkan)
            and (min_low_since_flip > first_psar - 0.618 * diff_mes)
            and (close_mes < open_mes)
            and not self.has_open_position()
        )

        # ----------------------------------------------------------------------
        # 5. Exit conditions                                                    |
        # ----------------------------------------------------------------------

        exit_signal = False

        # PSAR trailing stop equivalent ----------------------------------------
        if self.has_open_position():
            for pos in self.params.positions:
                size = pos.get("position", 0)
                if size == 0:
                    continue

                if size > 0:  # LONG – stop when PSAR above price
                    if psar_mes >= close_mes:
                        exit_signal = True
                elif size < 0:  # SHORT – stop when PSAR below price
                    if psar_mes <= close_mes:
                        exit_signal = True

        # Weekly exit (Friday candle closes contrary to weekly open) -----------
        is_weekly_candle, current_candle, prev_candle = self._get_weekly_candle(mes_data)
        if is_weekly_candle and self.has_open_position():
            weekly_open = current_candle["open"]
            weekly_close = current_candle["close"]
            for pos in self.params.positions:
                size = pos.get("position", 0)
                if size > 0 and weekly_close < weekly_open:
                    exit_signal = True
                elif size < 0 and weekly_close > weekly_open:
                    exit_signal = True

        # Entry candle validation (immediate exit) -----------------------------
        psar_mym = psar_mym_series[-1]
        if self._check_entry_candle_validation(mes_data, mym_data, psar_mes, psar_mym):
            exit_signal = True

        # ----------------------------------------------------------------------
        # 6. Decision tree                                                      |
        # ----------------------------------------------------------------------

        # ----------------------------------------------------------------------
        # 7. Determine contract sizing (6 vs 12)                                |
        # ----------------------------------------------------------------------

        qty = 0  # default until we know

        if buy_initial:
            qty = 12
        elif sell_initial:
            qty = 12
        elif buy_reentry:
            level_38 = first_psar + 0.382 * diff_mes
            qty = 12 if close_mes < level_38 else 6
        elif sell_reentry:
            level_38 = first_psar - 0.382 * diff_mes
            qty = 12 if close_mes > level_38 else 6

        # Persist the qty so create_orders() can use it
        if qty:
            self.params.number_of_contracts = qty

        # ----------------------------------------------------------------------
        # 8. Final decision                                                     |
        # ----------------------------------------------------------------------

        if buy_initial or buy_reentry:
            logger.warning(f"IchimokuBase -> LONG signal generated ({qty} contracts)")
            return "LONG"
        if sell_initial or sell_reentry:
            logger.warning(f"IchimokuBase -> SHORT signal generated ({qty} contracts)")
            return "SHORT"
        if exit_signal:
            logger.warning("IchimokuBase -> EXIT signal generated")
            return "EXIT"

        logger.info("IchimokuBase -> STAY (no actionable signal)")
        return "STAY"
    
    def backtest(self):
        """Replay historical data to evaluate strategy performance.

        The routine mimics real-time operation by revealing candles one at a time
        to `self.run()` and capturing the resulting LONG / SHORT / EXIT / STAY
        decisions.  Each completed trade is stored in a `TradeSnapshot` object.
        """

        # Reset runtime collections ------------------------------------------------
        self.params.open_orders = []
        self.params.executed_orders = []
        self.params.positions = []

        mes_contract = self.params.get_mes_data()
        mym_contract = self.params.get_mym_data()

        if not (mes_contract and mym_contract):
            logger.error("Backtest requires both MES and MYM data – aborting")
            return []

        full_mes = mes_contract.data
        full_mym = mym_contract.data

        num_candles = min(len(full_mes), len(full_mym))
        logger.info(f"Backtest will replay {num_candles} candles (MES/MYM synchronised).")

        open_trade = None
        trades = []
        decisions = []  # NEW list to capture every decision chronologically

        # Iterate candle-by-candle -------------------------------------------------
        for idx in range(num_candles):

            # Supply truncated history up to *including* idx to the strategy
            mes_contract.data = full_mes[: idx + 1]
            mym_contract.data = full_mym[: idx + 1]

            decision = self.run()
            # Record decision with timestamp for frontend usage
            current_candle = full_mes[idx]
            
            current_date = current_candle.get("date")
            current_close = current_candle.get("close")
            decisions.append({
                'date': current_date.strftime('%Y%m%d%H%M%S'),
                'decision': decision
            })

            qty = getattr(self.params, "number_of_contracts", 1) or 1

            # Handle decisions ---------------------------------------------------
            if decision in ("LONG", "SHORT") and open_trade is None:
                # New position opened
                open_trade = TradeSnapshot(
                    side=decision,
                    qty=qty,
                    entry_date=current_date,
                    entry_price=current_close,
                )
                logger.warning(f"Opened {decision} on {current_date} @ {current_close} ({qty} contracts)")

                # Reflect open position so that self.run() is aware
                self.params.positions = [{"position": qty if decision == "LONG" else -qty}]

            elif decision == "EXIT" and open_trade is not None:
                # Close existing position
                open_trade.close(current_date, current_close, "EXIT_SIGNAL")
                trades.append(open_trade)
                logger.info(f"Closed position on {current_date} @ {current_close}")
                open_trade = None
                self.params.positions = []

            # Otherwise (STAY), nothing to do.

        # Close any open position at the dataset end -----------------------------
        if open_trade is not None:
            open_trade.close(full_mes[-1].get("date"), full_mes[-1].get("close"), "END_OF_DATA")
            trades.append(open_trade)
            self.params.positions = []

        logger.success(f"Backtest generated {len(trades)} trades.")
        return trades, decisions

    def create_orders(self, action: str):
        mes_data = self.params.get_mes_data()
        mym_data = self.params.get_mym_data()
        
        if not mes_data or not mes_data.data:
            logger.error("No MES data available for order creation")
            return None
        
        if not mym_data or not mym_data.data:
            logger.error("No MYM data available for order creation")
            return None

        # Get entry prices from PSAR
        mes_psar_price = self.params.contracts[0].indicators['psar'][-1] if self.params.contracts[0].indicators['psar'] else mes_data.data[-1]['close']
        mym_psar_price = self.params.contracts[1].indicators['psar'][-1] if self.params.contracts[1].indicators['psar'] else mym_data.data[-1]['close']
        
        # Get the PSAR difference for calculating TP levels
        difference = getattr(self.params, 'psar_difference', 0)
        qty = self.params.number_of_contracts
        
        if action == 'LONG':
            tp1_qty = min(6, qty // 2) if qty <= 12 else 6
            tp2_qty = qty - tp1_qty
        else:
            tp1_qty = min(2, qty // 2) if qty <= 4 else 2
            tp2_qty = qty - tp1_qty

        logger.info(f"Creating {action} order with {qty} contracts")
        logger.info(f"MES entry price: {mes_psar_price:.2f}, MYM entry price: {mym_psar_price:.2f}")
        logger.info(f"PSAR difference: {difference:.2f}")

        if action == 'LONG':
            entry_price = mes_psar_price
            sl_price = mes_psar_price
            
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

            return [parent, stop_loss, tp1, tp2]
        
        else:
            logger.info(f"No order created for action: {action}")
            return None

    def _calculate_tenkan(self, data):
        last_5_days_mes = data[-5:]
        max_high_mes_5 = max(day['high'] for day in last_5_days_mes)
        min_low_mes_5 = min(day['low'] for day in last_5_days_mes)
        return 0.5 * (max_high_mes_5 + min_low_mes_5)
    
    def _calculate_kijun(self, data):
        last_21_days_mes = data[-21:]
        max_high_mes_21 = max(day['high'] for day in last_21_days_mes)
        min_low_mes_21 = min(day['low'] for day in last_21_days_mes)
        return 0.5 * (max_high_mes_21 + min_low_mes_21)

    def _calculate_parabolic_sar(self, data, start_af=0.02, increment_af=0.02, max_af=0.20):
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

    def _is_psar_positive(self, current_psar: float, data: list):
        # PSAR is positive when it's above the price (per specification)
        if current_psar > data[-1]['close']:
            return True
        else:
            return False

    def _is_psar_negative(self, current_psar: float, data: list):
        return not self._is_psar_positive(current_psar, data)

    def _find_recent_trend_change(self, psar_data, historical_data, lookback=4):
        """Check if there was a trend change from negative to positive in last 4 candles"""
        if len(psar_data) < lookback + 1:
            return False, lookback + 1
        
        # Look at the last few candles
        for i in range(1, lookback + 1):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            # Check if there was a change from negative to positive
            if (self._is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self._is_psar_positive(current_psar, [historical_data[-i]])):
                return True, i
        
        return False, lookback + 1  # Return a value larger than lookback to indicate no recent change

    def _find_recent_downtrend_change(self, psar_data, historical_data, lookback=4):
        """Check if there was a trend change from positive to negative in last 4 candles"""
        if len(psar_data) < lookback + 1:
            return False, lookback + 1
        
        # Look at the last few candles
        for i in range(1, lookback + 1):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            # Check if there was a change from positive to negative
            if (self._is_psar_positive(prev_psar, [historical_data[-(i+1)]]) and 
                self._is_psar_negative(current_psar, [historical_data[-i]])):
                return True, i
        
        return False, lookback + 1  # Return a value larger than lookback to indicate no recent change

    def _calculate_highest_high_since_change(self, historical_data, candles_since_change):
        """Calculate the highest high since the trend changed"""
        relevant_data = historical_data[-candles_since_change:]
        return max(day['high'] for day in relevant_data)
    
    def _calculate_lowest_low_since_change(self, historical_data, candles_since_change):
        """Calculate the lowest low since the trend changed"""
        relevant_data = historical_data[-candles_since_change:]
        return min(day['low'] for day in relevant_data)

    def _get_trend_change_psars(self, psar_data, historical_data):
        """Get the last PSAR of previous downtrend and first PSAR of current uptrend"""
        for i in range(1, len(psar_data)):
            current_psar = psar_data[-i]
            prev_psar = psar_data[-(i+1)]
            
            if (self._is_psar_negative(prev_psar, [historical_data[-(i+1)]]) and 
                self._is_psar_positive(current_psar, [historical_data[-i]])):
                return prev_psar, current_psar
        
        return None, None

    def _get_weekly_candle(self, data):
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
                            if self._is_psar_negative(psar_mym, [mym_data[-1]]):
                                logger.warning(f"Entry candle validation: LONG position but MYM PSAR is negative - exit")
                                return True
                        
                        # Check if it's a SHORT position
                        elif position['position'] < 0:
                            # For SHORT position, exit if current candle is green (close > open)
                            if current_candle['close'] > current_candle['open']:
                                logger.warning(f"Entry candle validation: SHORT position with green candle - exit")
                                return True
                            
                            # Check PSAR alignment - MYM should also be negative for SHORT
                            if self._is_psar_positive(psar_mym, [mym_data[-1]]):
                                logger.warning(f"Entry candle validation: SHORT position but MYM PSAR is positive - exit")
                                return True
        
        return False

class SMACrossover(Strategy):
    """Simple strategy that generates LONG/SHORT signals based on a 200-period SMA crossover"""

    def __init__(self, initialParams: SMACrossoverParams):
        super().__init__(initialParams)
        self.name = 'SMA Crossover'
        self.timeframe = '1 hour'
        self.timeframe_seconds = 3600

    def to_dict(self):
        return {
            'name': self.name,
            **super().to_dict()
        }

    def refresh_params(self, data_manager):
        logger.announcement("Refreshing strategy params...", 'info')
        self.params.open_orders = data_manager.get_open_orders()
        self.params.executed_orders = data_manager.get_completed_orders()
        self.params.positions = data_manager.get_positions()
        self.params.contracts[0].data = data_manager.get_historical_data(self.params.contracts[0].contract, duration='1 Y', bar_size=self.timeframe)
        logger.success("Strategy params refreshed")

    def run(self):

        logger.announcement('Executing strategy...', 'info')
        main_contract = self.params.contracts[0]

        if not main_contract:
            logger.error('No data available')
            return 'STAY'

        if len(main_contract.data) < 201:
            logger.warning('Not enough data for calculation')
            return 'STAY'
        
        # Calculate 200-period Simple Moving Average (SMA)
        window = 200
        sma_values = [
            np.mean([d['close'] for d in main_contract.data[max(0, i - window):i]])
            for i in range(1, len(main_contract.data) + 1)
        ]

        # Save historical SMA values to indicators
        main_contract.indicators['sma'] = sma_values

        # Get the latest SMA value
        sma = sma_values[-1]
        self.params.indicators['sma'] = sma
        prev_sma = sma_values[-2]

        latest_close = main_contract.data[-1]['close']
        prev_close = main_contract.data[-2]['close']

        logger.info(
            f"Latest close: {latest_close:.2f}, Prev close: {prev_close:.2f}, "
            f"SMA: {sma:.2f}, Prev SMA: {prev_sma:.2f}"
        )

        has_position = self.has_open_position()
        # Entry condition: price crosses above SMA (bullish crossover)
        if not has_position and prev_close <= prev_sma and latest_close > sma:
            logger.warning('Bullish crossover detected -> LONG')
            return 'LONG'

        # Exit condition: price crosses below SMA (bearish cross-under)
        elif prev_close >= prev_sma and latest_close < sma:
            logger.warning('Bearish cross-under detected -> EXIT')
            return 'EXIT'

        logger.info('No crossover detected -> STAY')
        return 'STAY'

    def backtest(self):
        """
        """

        self.params.open_orders = []
        self.params.executed_orders = []
        self.params.positions = []

        full_historical_data = self.params.contracts[0].data
        logger.info(f"Backtest will replay {len(full_historical_data)} candles.")

        open_trade = None
        trades = []
        decisions = []  # NEW: keep a record of every decision taken

        # Iterate through each candle and progressively grow the data set that the strategy can see.
        for idx, candle in enumerate(full_historical_data):

            # The SMA-200 requires at least 201 price points (previous close + current close).
            # Skip the initial period where we do not have enough data to evaluate a signal.
            if idx < 200:
                continue

            # Provide the strategy only with data **up to** the current index so that run() "sees"
            # market information as it would have been available on that day.
            self.params.contracts[0].data = full_historical_data[: idx + 1]

            # Execute the strategy on this truncated data set
            decision = self.run()

            # Record the decision for this candle
            current_date = candle.get('date')
            current_close = candle.get('close')
            
            decisions.append({
                'date': current_date.strftime('%Y%m%d%H%M%S'),
                'decision': decision
            })

            qty = getattr(self.params, 'number_of_contracts', 1)

            if decision in ("LONG", "SHORT") and open_trade is None:
                open_trade = TradeSnapshot(
                    side=decision,
                    qty=qty,
                    entry_date=current_date,
                    entry_price=current_close,
                )
                logger.warning(
                    f"Opened {decision} on {current_date} @ {current_close} ({qty} contracts)"
                )
                # Reflect open position in strategy params so that subsequent run() calls know
                self.params.positions = [{'position': qty if decision == 'LONG' else -qty}]

            elif decision == "EXIT" and open_trade is not None:
                open_trade.close(current_date, current_close, "EXIT_SIGNAL")
                trades.append(open_trade)
                logger.info(f"Closed position on {current_date} @ {current_close}")
                open_trade = None
                self.params.positions = []

        # Close any remaining open position at the end of the data set
        if open_trade is not None:
            open_trade.close(
                full_historical_data[-1].get('date'),
                full_historical_data[-1].get('close'),
                "END_OF_DATA",
            )
            trades.append(open_trade)
            self.params.positions = []

        logger.success(f"Backtest generated {len(trades)} trades.")
        # Return both trades and full decision history
        return trades, decisions

    def create_orders(self, action: str):
        
        main_contract = self.params.contracts[0]
        if not main_contract:
            logger.error('No data available for order creation')
            return None
        
        main_contract_data = main_contract.data[-1]

        qty = 10  # number of shares
        entry_price = main_contract_data.get('close')
        if entry_price is None:
            logger.error('Could not determine entry price')
            return None

        if action == 'LONG':
            order = MarketOrder(action='BUY', totalQuantity=qty)
        elif action == 'SHORT':
            order = MarketOrder(action='SELL', totalQuantity=qty)
        else:
            logger.info(f'No order created for action: {action}')
            return None

        logger.info(f'Creating {action} market order for {qty} AAPL shares at approx {entry_price:.2f}')
        return [order]