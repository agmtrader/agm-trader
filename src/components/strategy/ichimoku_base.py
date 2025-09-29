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
        # NOTE: Replace with correct futures contracts when integrating with live trading
        mes_contract = Stock('MES', 'SMART', 'USD')  # placeholder for Micro E-mini S&P 500 futures
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
        self.name = 'Ichimoku Base (PSAR)'
        self.timeframe = '1 day'
        self.timeframe_seconds = 86400
        # Internal state tracking
        self._prev_psar_sign = None  # +1 => bearish, -1 => bullish

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
            self.params.contracts[0].contract, duration='6 M', bar_size=self.timeframe
        )
        logger.success("Params refreshed.")

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

        logger.info(
            f"Prev sign: {prev_sign}, Latest sign: {latest_sign}, Prev PSAR: {prev_psar:.2f}, "
            f"Latest PSAR: {latest_psar:.2f}, Latest close: {latest_close:.2f}"
        )

        has_position = self.has_open_position()

        # Entry rule: Flip to bullish trend and no open position
        if not has_position and prev_sign == 1 and latest_sign == -1:
            logger.warning('PSAR flip to bullish detected -> LONG')
            return 'LONG'

        # Exit rule: Holding position and PSAR flips bearish
        if has_position and prev_sign == -1 and latest_sign == 1:
            logger.warning('PSAR flip to bearish detected -> EXIT')
            return 'EXIT'

        logger.info('No actionable PSAR flip -> STAY')
        return 'STAY'

    # ------------------------------------------------------------------
    def backtest(self):
        """Basic backtest like the SMA crossover implementation."""
        self.params.open_orders = []
        self.params.executed_orders = []
        self.params.positions = []

        full_historical_data = self.params.contracts[0].data
        logger.info(f"Backtest will replay {len(full_historical_data)} candles (Ichimoku Base).")

        open_trade = None
        trades = []
        decisions = []

        for idx, candle in enumerate(full_historical_data):
            if idx < 5:
                continue  # need a few candles to stabilise PSAR

            self.params.contracts[0].data = full_historical_data[: idx + 1]
            decision = self.run()

            current_date = candle.get('date')
            current_close = candle.get('close')
            decisions.append({
                'date': current_date.strftime('%Y%m%d%H%M%S') if current_date else str(idx),
                'decision': decision
            })

            qty = getattr(self.params, 'number_of_contracts', 1)

            if decision == 'LONG' and open_trade is None:
                open_trade = TradeSnapshot(
                    side='LONG',
                    qty=qty,
                    entry_date=current_date,
                    entry_price=current_close,
                )
                logger.info(f"Opened LONG on {current_date} @ {current_close} ({qty} contracts)")
                self.params.positions = [{'position': qty}]

            elif decision == 'EXIT' and open_trade is not None:
                open_trade.close(current_date, current_close, 'EXIT_SIGNAL')
                trades.append(open_trade)
                logger.info(f"Closed position on {current_date} @ {current_close}")
                open_trade = None
                self.params.positions = []

        logger.success(f"Backtest generated {len(trades)} trades (Ichimoku Base).")
        return trades, decisions

    # ------------------------------------------------------------------
    def create_orders(self, action: str):
        main_contract = self.params.contracts[0]
        if not main_contract:
            logger.error('No data available for order creation')
            return None

        main_contract_data = main_contract.data[-1]
        qty = 12  # default contract size for this strategy
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

        logger.info(f'Creating {action} market order for {qty} contracts at approx {entry_price:.2f}')
        return [order]
