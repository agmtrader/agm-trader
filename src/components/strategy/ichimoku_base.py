from src.lib.params import BaseStrategyParams, ContractData
from src.lib.strategy import Strategy
from src.utils.logger import logger
import numpy as np
from typing import Dict, Any, List
from ib_insync import *
from src.lib.trade_snapshot import TradeSnapshot

class IchimokuBaseParams(BaseStrategyParams):
    """Parameters container for the Ichimoku (PSAR-based) strategy"""

    def __init__(self):
        super().__init__()
        contract_month = '202512'
        mes_contract = Future('MES', contract_month, 'CME')
        self.contracts = [ContractData(mes_contract)]
        self.indicators = {
            'psar': []
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'indicators': self.indicators,
            **super().to_dict(),
        }

class IchimokuBase(Strategy):
    """Simplified implementation of the “ICHIMOKU BASE” strategy using PSAR flips.

    This version mirrors the structure of `SMACrossover` and focuses on generating
    LONG / EXIT / STAY signals based on PSAR sign changes. It can be gradually
    extended to include the full set of rules (limit entries, add-ons, TP levels, etc.).
    """

    def __init__(self, initialParams: IchimokuBaseParams):
        super().__init__(initialParams)
        self.name = 'ICHIMOKU_BASE'
        self.timeframe = '1 day'
        self.timeframe_seconds = 86400
        # Internal state tracking
        self._prev_psar_sign = None  # +1 => bearish, -1 => bullish
        # New: attributes for full trend tracking
        self.trend_direction = None  # 'long', 'short', or None
        self.trend_start_idx = None
        self.candle_count = 0
        self.last_prev_psar = None
        self.first_psar = None
        self.diff = None
        self.max_high_since_start = None
        self.min_low_since_start = None
        # Take-profit tracking
        self.tp1_level = None
        self.tp2_level = None
        self.tp1_hit = False

    # ---------------------------------------------------------------------
    # Utility helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _calculate_psar(high: List[float], low: List[float], step: float = 0.02, max_step: float = 0.2) -> List[float]:
        """Return full Parabolic SAR series for the given high and low arrays.

        This is a pure-python implementation adapted from commonly used formulas. It
        should be sufficient for daily data sizes (< 10k bars). For production use
        you may prefer TA-Lib or pandas_ta for speed and reliability.
        """
        if len(high) != len(low):
            raise ValueError("High and Low arrays must be the same length")

        n = len(high)
        psar = [np.nan] * n

        # Initial trend assumption: use first two closes to decide
        trend_up = True  # default
        if n >= 2:
            trend_up = high[1] >= high[0]  # crude proxy

        # Initial Extreme Point (EP) and SAR
        ep = high[0] if trend_up else low[0]
        sar = low[0] if trend_up else high[0]
        af = step

        psar[0] = sar

        for i in range(1, n):
            # 1) Calculate next SAR value
            sar = sar + af * (ep - sar)

            # 2) In uptrend, SAR cannot be above prior two lows
            if trend_up:
                if i >= 2:
                    sar = min(sar, low[i - 1], low[i - 2])
                elif i == 1:
                    sar = min(sar, low[i - 1])
            else:  # downtrend: SAR cannot be below prior two highs
                if i >= 2:
                    sar = max(sar, high[i - 1], high[i - 2])
                elif i == 1:
                    sar = max(sar, high[i - 1])

            # 3) Check for trend switch
            reversed_ = False
            if trend_up:
                if low[i] < sar:
                    trend_up = False
                    sar = ep  # On reversal, SAR is set to previous EP
                    ep = low[i]
                    af = step
                    reversed_ = True
            else:
                if high[i] > sar:
                    trend_up = True
                    sar = ep
                    ep = high[i]
                    af = step
                    reversed_ = True

            # 4) Update EP & AF
            if trend_up:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + step, max_step)
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + step, max_step)

            psar[i] = sar

        return psar

    # ------------------------------------------------------------------
    def to_dict(self):
        return {
            'name': self.name,
            'trend': self.trend_direction,
            'tp1': self.tp1_level,
            'tp2': self.tp2_level,
            'diff': self.diff,
            **super().to_dict(),
        }

    # ------------------------------------------------------------------
    def refresh_params(self, data_manager):
        logger.info("Refreshing strategy params (Ichimoku Base)...")
        self.params.open_orders = data_manager.get_open_orders()
        self.params.executed_orders = data_manager.get_completed_orders()
        self.params.positions = data_manager.get_positions()
        # Fetch 6 months of daily data as a starting point
        self.params.contracts[0].data = data_manager.get_historical_data(
            self.params.contracts[0].contract, duration='1 Y', bar_size=self.timeframe
        )
        logger.success("Params refreshed.")

        # Return the updated params so that caller can persist the latest snapshot
        return self.params

    # ------------------------------------------------------------------
    def run(self):
        logger.announcement('Executing Ichimoku Base strategy...', 'info')
        main_contract = self.params.contracts[0]

        if not main_contract or len(main_contract.data) < 5:
            logger.warning('Not enough data to evaluate strategy')
            return 'STAY'

        highs = [d['high'] for d in main_contract.data]
        lows = [d['low'] for d in main_contract.data]
        closes = [d['close'] for d in main_contract.data]

        psar_series = self._calculate_psar(highs, lows)
        main_contract.indicators['psar'] = psar_series
        self.params.indicators['psar'] = psar_series[-1]

        # Determine PSAR sign for latest and previous candle
        latest_psar = psar_series[-1]
        prev_psar = psar_series[-2]
        latest_close = closes[-1]
        prev_close = closes[-2]

        latest_sign = -1 if latest_psar < latest_close else 1  # -1 bullish, +1 bearish
        prev_sign = -1 if prev_psar < prev_close else 1

        # --------------------------------------------------------------
        # Update internal trend state
        # --------------------------------------------------------------
        if latest_sign != prev_sign:
            # A flip occurred – define new trend baseline
            self.trend_direction = 'long' if latest_sign == -1 else 'short'
            self.trend_start_idx = len(psar_series) - 1
            self.candle_count = 1
            self.last_prev_psar = prev_psar
            self.first_psar = latest_psar
            self.diff = abs(self.last_prev_psar - self.first_psar)
            # Compute TP levels
            if self.trend_direction == 'long':
                self.tp1_level = self.last_prev_psar + 0.382 * self.diff
                self.tp2_level = self.last_prev_psar + 0.5 * self.diff
            else:
                self.tp1_level = self.last_prev_psar - 0.382 * self.diff
                self.tp2_level = self.last_prev_psar - 0.5 * self.diff
            self.tp1_hit = False
            # Reset extremes
            self.max_high_since_start = highs[-1]
            self.min_low_since_start = lows[-1]
        else:
            # Same trend – increment counters and update extremes
            if self.trend_direction is not None:
                self.candle_count += 1
                self.max_high_since_start = (
                    max(self.max_high_since_start, highs[-1]) if self.max_high_since_start is not None else highs[-1]
                )
                self.min_low_since_start = (
                    min(self.min_low_since_start, lows[-1]) if self.min_low_since_start is not None else lows[-1]
                )

        logger.info(
            f"Prev sign: {prev_sign}, Latest sign: {latest_sign}, Prev PSAR: {prev_psar:.2f}, "
            f"Latest PSAR: {latest_psar:.2f}, Latest close: {latest_close:.2f}, Trend: {self.trend_direction}, "
            f"Candle# {self.candle_count}"
        )

        has_position = self.has_open_position()

        # --------------------------------------------------------------
        # Stop-loss exit using PSAR as trailing level
        # --------------------------------------------------------------
        if has_position and self.trend_direction is not None:
            position_dir = self._get_position_direction()
            if position_dir == 'long':
                if lows[-1] <= latest_psar:
                    logger.warning('PSAR stop-loss hit for LONG -> EXIT')
                    return 'EXIT'
            elif position_dir == 'short':
                if highs[-1] >= latest_psar:
                    logger.warning('PSAR stop-loss hit for SHORT -> EXIT')
                    return 'EXIT'

        # --------------------------------------------------------------
        # Take-profit handling (partial exits and full close)
        # --------------------------------------------------------------
        if has_position and self.tp1_level is not None and self.tp2_level is not None:
            position_dir = self._get_position_direction()

            # ---- LONG ----
            if position_dir == 'long':
                # TP2 overrides
                if highs[-1] >= self.tp2_level:
                    logger.warning('TP2 reached for LONG -> EXIT')
                    return 'EXIT'

                # TP1 partial
                if not self.tp1_hit and highs[-1] >= self.tp1_level:
                    self.tp1_hit = True
                    logger.warning('TP1 reached for LONG -> PARTIAL_EXIT_6')
                    return 'PARTIAL_EXIT_6'

                # After TP1, contrary close exits rest
                if self.tp1_hit and closes[-1] < self.tp1_level:
                    logger.warning('Close below TP1 after TP1 hit -> EXIT')
                    return 'EXIT'

            # ---- SHORT ----
            if position_dir == 'short':
                if lows[-1] <= self.tp2_level:
                    logger.warning('TP2 reached for SHORT -> EXIT')
                    return 'EXIT'

                if not self.tp1_hit and lows[-1] <= self.tp1_level:
                    self.tp1_hit = True
                    logger.warning('TP1 reached for SHORT -> PARTIAL_EXIT_6')
                    return 'PARTIAL_EXIT_6'

                if self.tp1_hit and closes[-1] > self.tp1_level:
                    logger.warning('Close above TP1 after TP1 hit -> EXIT')
                    return 'EXIT'

        # --------------------------------------------------------------
        # Primary entry signals (flip-based)
        # --------------------------------------------------------------
        if not has_position:
            if prev_sign == 1 and latest_sign == -1:
                logger.warning('PSAR flip to bullish detected -> LONG')
                return 'LONG'
            if prev_sign == -1 and latest_sign == 1:
                logger.warning('PSAR flip to bearish detected -> SHORT')
                return 'SHORT'

        # --------------------------------------------------------------
        # Add-on / re-entry logic (within first 4 candles of new trend)
        # --------------------------------------------------------------
        if has_position and self.candle_count <= 4 and self.diff is not None:
            position_dir = self._get_position_direction()

            # LONG add-on conditions
            if position_dir == 'long' and self.trend_direction == 'long':
                cond_price = latest_close > self.last_prev_psar
                cond_high_max = self.max_high_since_start < (self.last_prev_psar + 0.5 * self.diff)
                if cond_price and cond_high_max:
                    add_qty = 12 if latest_close < (self.last_prev_psar + 0.382 * self.diff) else 6
                    logger.warning(f'Add-on LONG signal ({add_qty} contracts)')
                    return f'ADD_LONG_{add_qty}'

            # SHORT add-on conditions
            if position_dir == 'short' and self.trend_direction == 'short':
                cond_price = latest_close < self.last_prev_psar
                cond_low_min = self.min_low_since_start > (self.last_prev_psar - 0.5 * self.diff)
                if cond_price and cond_low_min:
                    add_qty = 12 if latest_close > (self.last_prev_psar - 0.382 * self.diff) else 6
                    logger.warning(f'Add-on SHORT signal ({add_qty} contracts)')
                    return f'ADD_SHORT_{add_qty}'

        # --------------------------------------------------------------
        # Exit logic for flips handled earlier, risk-management to come
        # --------------------------------------------------------------

        logger.info('No actionable signal -> STAY')
        return 'STAY'

    # ------------------------------------------------------------------
    def backtest(self):
        """Enhanced backtest supporting add-ons, TP & SL partial exits."""
        self.params.open_orders = []
        self.params.executed_orders = []
        self.params.positions = []  # List[dict]: {'qty':int,'side':str,'entry_price':float,'tp1_hit':bool}

        full_historical_data = self.params.contracts[0].data
        logger.info(f"Backtest will replay {len(full_historical_data)} candles (Ichimoku Base).")

        open_batches: List[TradeSnapshot] = []  # For tracking trade snapshots per batch
        completed_trades: List[TradeSnapshot] = []
        decisions = []

        for idx, candle in enumerate(full_historical_data):
            if idx < 5:
                continue

            # Slice data up to current index
            self.params.contracts[0].data = full_historical_data[: idx + 1]
            decision = self.run()

            current_date = candle.get('date')
            current_close = candle.get('close')
            decisions.append({'date': current_date.strftime('%Y%m%d') if current_date else str(idx), 'decision': decision})

            # Helper to append snapshot and manage pos list
            def open_batch(side: str, qty: int, price: float):
                snap = TradeSnapshot(side=side.upper(), qty=qty, entry_date=current_date, entry_price=price)
                open_batches.append(snap)
                self.params.positions.append({'position': qty if side=='long' else -qty})

            def close_batches(qty_to_close: int, price: float, reason: str):
                remaining = qty_to_close
                while remaining > 0 and open_batches:
                    snap = open_batches[0]
                    if snap.qty <= remaining:
                        close_qty = snap.qty
                        remaining -= close_qty
                        snap.close(current_date, price, reason)
                        completed_trades.append(snap)
                        open_batches.pop(0)
                    else:
                        # Partial within snapshot
                        part_snap = TradeSnapshot(side=snap.side, qty=remaining, entry_date=snap.entry_date, entry_price=snap.entry_price)
                        part_snap.close(current_date, price, reason)
                        completed_trades.append(part_snap)
                        snap.qty -= remaining
                        remaining = 0
                # Update positions list
                self.params.positions = [{'position': b.qty if b.side=='LONG' else -b.qty} for b in open_batches]

            # Map decisions to actions
            if decision == 'LONG':
                entry_price = self.last_prev_psar if self.last_prev_psar is not None else current_close
                open_batch('long', 12, entry_price)
            elif decision == 'SHORT':
                entry_price = self.last_prev_psar if self.last_prev_psar is not None else current_close
                open_batch('short', 12, entry_price)
            elif decision.startswith('ADD_LONG_'):
                qty_add = int(decision.split('_')[-1])
                open_batch('long', qty_add, current_close)
            elif decision.startswith('ADD_SHORT_'):
                qty_add = int(decision.split('_')[-1])
                open_batch('short', qty_add, current_close)
            elif decision.startswith('PARTIAL_EXIT_'):
                qty_exit = int(decision.split('_')[-1])
                close_price = self.tp1_level if self.tp1_level is not None else current_close
                close_batches(qty_exit, close_price, 'TP1')
            elif decision == 'EXIT':
                total_qty = sum(b.qty for b in open_batches)
                close_batches(total_qty, current_close, 'EXIT_SIGNAL')

        # Close remaining at end of data
        for snap in open_batches:
            snap.close(full_historical_data[-1].get('date'), full_historical_data[-1].get('close'), 'END_OF_DATA')
            completed_trades.append(snap)

        logger.success(f"Backtest generated {len(completed_trades)} trades (Ichimoku Base).")
        return completed_trades, decisions

    # ------------------------------------------------------------------
    def create_orders(self, action: str):
        main_contract = self.params.contracts[0]
        if not main_contract:
            logger.error('No data available for order creation')
            return None

        latest_data = main_contract.data[-1]
        # Default quantities
        default_entry_qty = 12

        # Determine limit prices
        price_psar_prev = self.last_prev_psar if self.last_prev_psar is not None else latest_data.get('close')
        price_tp1 = self.tp1_level if self.tp1_level is not None else latest_data.get('close')

        def lmt(side: str, qty: int, price: float):
            return LimitOrder(action=side, lmtPrice=round(price, 2), totalQuantity=qty)

        if action == 'LONG':
            return [lmt('BUY', default_entry_qty, price_psar_prev)]
        if action == 'SHORT':
            return [lmt('SELL', default_entry_qty, price_psar_prev)]

        if action.startswith('ADD_LONG_'):
            qty_add = int(action.split('_')[-1])
            return [lmt('BUY', qty_add, latest_data.get('close'))]
        if action.startswith('ADD_SHORT_'):
            qty_add = int(action.split('_')[-1])
            return [lmt('SELL', qty_add, latest_data.get('close'))]

        if action.startswith('PARTIAL_EXIT_'):
            qty_exit = int(action.split('_')[-1])
            side_action = 'SELL' if self._get_position_direction() == 'long' else 'BUY'
            return [lmt(side_action, qty_exit, price_tp1)]

        if action == 'EXIT':
            # Close entire position at market
            side_action = 'SELL' if self._get_position_direction() == 'long' else 'BUY'
            total_qty = sum(abs(p.get('position',0)) for p in self.params.positions)
            return [MarketOrder(action=side_action, totalQuantity=total_qty)]

        logger.info(f'No order created for action: {action}')
        return None

    # ------------------------------------------------------------------
    def _get_position_direction(self):
        """Infer current position direction from params.positions list."""
        for pos in getattr(self.params, 'positions', []):
            size = pos.get('position', 0)
            if size > 0:
                return 'long'
            elif size < 0:
                return 'short'
        return None
