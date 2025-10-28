from src.lib.params import BaseStrategyParams, ContractData
from src.lib.strategy import Strategy
from src.utils.logger import logger
import numpy as np
from ib_insync import *
from typing import Dict, Any
from src.lib.trade_snapshot import TradeSnapshot

class SMACrossoverParams(BaseStrategyParams):
    """Parameters container for the SMA crossover strategy"""

    def __init__(self):
        super().__init__()
        contract = Stock('MA', 'SMART', 'USD')
        self.contracts = [ContractData(contract)]
        self.indicators = {
            'sma': 0
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'indicators': self.indicators,
            **super().to_dict(),
        }


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
        logger.info("Refreshing strategy params...")
        self.params.open_orders = data_manager.get_open_orders()
        self.params.executed_orders = data_manager.get_completed_orders()
        self.params.positions = data_manager.get_positions()
        self.params.contracts[0].data = data_manager.get_historical_data(self.params.contracts[0].contract, duration='3 M', bar_size=self.timeframe)
        logger.success("Successfully refreshed strategy params.")

        # Return the updated params so caller can persist changes over time
        return self.params

    def run(self):

        logger.announcement('Executing strategy...', 'info')
        main_contract = self.params.contracts[0]

        if not main_contract:
            logger.error('No data available')
            return 'STAY'

        if len(main_contract.data) < 201:
            logger.info('Not enough data for calculation')
            return 'STAY'
        
        # Calculate 50-period Simple Moving Average (SMA)
        window = 50
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

        # Exit only if we currently hold an open position
        elif has_position and prev_close >= prev_sma and latest_close < sma:
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
                logger.info(
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

        # Note: We no longer automatically close positions at the end of data
        # Any open positions will remain open in the final results

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

        logger.info(f'Creating {action} market order for {qty} shares at approx {entry_price:.2f}')
        return [order]
