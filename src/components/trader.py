from ib_insync import *
from src.utils.logger import logger 
import pandas as pd
import threading
import nest_asyncio
from datetime import datetime
import time
from src.components.strategy import IchimokuBase
from src.lib.params import IchimokuBaseParams
from src.components.connection_manager import ConnectionManager
from src.components.data_manager import DataManager
from src.components.order_manager import OrderManager
from src.components.backtest import BacktestSnapshot

SLEEP_TIME = 86400

class Trader:

    def __init__(self):
        self.conn = ConnectionManager()
        self.ib = self.conn.ib
        self.data = DataManager(self.conn)
        self.order_mgr = OrderManager(self.conn)

        self.running = False
        self.strategy = None
        self.decision = None
        self.account_summary = None
        self.backtest = []

        self.conn.connect()

        try:
            self.conn.start_connection_monitor()

            self.trading_thread = threading.Thread(target=self.run, args=('ICHIMOKU_BASE',))
            self.trading_thread.start()
            nest_asyncio.apply()

        except Exception as e:
            logger.error(f"Error starting trading thread: {str(e)}")
            raise Exception(f"Error starting trading thread: {str(e)}")

    def run(self, strategy_name: str):

        if strategy_name == 'ICHIMOKU_BASE':
            strategy = IchimokuBase(IchimokuBaseParams())
            self.strategy = strategy
        else:
            raise Exception(f"Strategy {strategy_name} not found")
        
        self.account_summary = self.data.get_account_summary()
        self.strategy.refresh_params(self.data)
        self.backtest = self.execute_backtest()
        self.order_mgr.close_all_positions()

        logger.announcement(f"Running strategy: {self.strategy.name}", 'info')
        self.running = True
        
        try:
            while True:

                if not self.running:
                    self.conn.stop_connection_monitor()
                    exit()

                if self.conn.is_connected() or self.conn.reconnect():
                    self.account_summary = self.data.get_account_summary()
                    self.strategy.refresh_params(self.data)
                else:
                    logger.warning("Connection not available for trading. Monitor thread should be handling reconnection...")
                    time.sleep(SLEEP_TIME)
                    continue

                self.decision = self.strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                # Handle exit signals
                if self.decision == 'EXIT':
                    if self.conn.is_connected() or self.conn.reconnect():
                        self.order_mgr.close_all_positions()
                    continue

                # Create orders for the strategy and place them
                order = self.strategy.create_orders(self.decision)
                if self.conn.is_connected() or self.conn.reconnect():
                    if order:
                        # TODO: Uncomment the line below when ready for live trading
                        #self.place_order(order)
                        logger.warning("Order placement is currently disabled for safety")
                        logger.announcement(f"Order placed: {order}", 'success')
                    
                    # Refresh strategy params
                    self.account_summary = self.data.get_account_summary()
                    self.strategy.refresh_params(self.data)

                time.sleep(SLEEP_TIME)
                
        except Exception as e:
            logger.error(f"Error running strategy: {str(e)}")
            self.conn.stop_connection_monitor()
            raise Exception(f"Error running strategy: {str(e)}")

    def execute_backtest(self, duration: str = '2 Y', bar_size: str = '1 day', output_dir: str = './'):
        """Run an **offline** back-test of the already-initialised strategy.
        The method will:
        1. Download historical bars for every contract used by the strategy.
        2. Step through the history day-by-day, asking the strategy for a
           decision at each step and – where applicable – creating the orders
           (only kept locally, never sent to IBKR).
        3. Build an in-memory list of :class:`BacktestSnapshot` rows.
        4. Persist the results to *CSV* and finally return the list.

        Parameters
        ----------
        duration : str
            IBKR duration string passed to ``reqHistoricalData``.
        bar_size : str
            Bar size for historical download.
        output_dir : str
            Directory where the CSV will be written. Defaults to repo root.
        """

        logger.announcement("Starting back-test …", 'info')

        if not self.strategy:
            # Create a default strategy if backtest() is invoked directly.
            self.strategy = IchimokuBase(IchimokuBaseParams())

        # ------------------------------------------------------------------
        # 1. Pull historical bars for every contract ONCE.
        # ------------------------------------------------------------------
        full_history = {}
        for contract_data in self.strategy.params.contracts:
            symbol = contract_data.get_symbol()
            bars = self.data.get_historical_data(contract_data.contract,
                                                duration=duration,
                                                bar_size=bar_size)
            if not bars:
                raise RuntimeError(f"No historical data for {symbol}")
            full_history[symbol] = bars
            contract_data.data = []  # reset (will be filled incrementally)

        # Align to the shortest history length so both MES & MYM have data.
        min_length = min(len(b) for b in full_history.values())

        snapshots = []
        cumulative_pnl = 0.0
        current_position = None  # 'LONG' | 'SHORT' | None
        entry_price = 0.0
        entry_qty = 0

        # We need at least 21 bars before indicators are fully valid
        start_at = 22 if min_length > 22 else 0

        for idx in range(start_at, min_length):
            # ------------------------------------------------------------------
            # 2. Feed the strategy *incremental* history up to *idx*.
            # ------------------------------------------------------------------
            for contract_data in self.strategy.params.contracts:
                sym = contract_data.get_symbol()
                contract_data.data = full_history[sym][: idx + 1]

            # During back-test we manually feed historical bars; avoid additional
            # API hits. Positions/orders remain empty.
            self.strategy.refresh_params(self.data)

            decision = self.strategy.run()

            # Collect order details – purely informational.
            orders = self.strategy.create_orders(decision) if decision in ('LONG', 'SHORT') else None

            # ------------------------------------------------------------------
            # 3. Build snapshot row
            # ------------------------------------------------------------------
            mes_bar = full_history['MES'][idx]
            prev_close = full_history['MES'][idx - 1]['close'] if idx > 0 else mes_bar['close']

            entry_price_cell = ''
            exit_price_cell = ''
            pnl_cell = 0.0

            # Handle position bookkeeping
            if decision in ('LONG', 'SHORT') and current_position is None:
                current_position = decision
                entry_price = mes_bar['close']
                entry_qty = self.strategy.params.number_of_contracts
                entry_price_cell = entry_price

            elif decision == 'EXIT' and current_position is not None:
                exit_price = mes_bar['close']
                if current_position == 'LONG':
                    pnl_cell = (exit_price - entry_price) * entry_qty
                else:  # SHORT
                    pnl_cell = (entry_price - exit_price) * entry_qty

                cumulative_pnl += pnl_cell
                exit_price_cell = exit_price
                current_position = None
                entry_price = 0.0
                entry_qty = 0

            snapshot_row = {
                'Date': mes_bar['date'],
                'Open': mes_bar['open'],
                'High': mes_bar['high'],
                'Low': mes_bar['low'],
                'Close': mes_bar['close'],
                'Prev Close': prev_close,
                'Decision': decision,
                'EntryPrice': entry_price_cell,
                'ExitPrice': exit_price_cell,
                'P/L': round(pnl_cell, 2),
                'Cum. P/L': round(cumulative_pnl, 2),
            }

            snapshots.append(BacktestSnapshot(snapshot_row))

            # Optional: log each snapshot decision
            logger.info(f"Back-test {snapshot_row['Date']} → {decision}")

        # ------------------------------------------------------------------
        # 4. Export to CSV
        # ------------------------------------------------------------------
        snapshots_df = pd.DataFrame(snapshots)
        snapshots_df.to_csv('backtest.csv', index=False)

        logger.success(f"Back-test completed. Results written to backtest.csv")

        # Store internally and return
        self.backtest = snapshots
        return snapshots

class TraderSnapshot:

    def __init__(self, trader: Trader):
        logger.announcement("Creating Trader Snapshot", 'info')
        self.current_time = datetime.now()
        self.strategy = trader.strategy
        self.decision = trader.decision
        self.account_summary = trader.account_summary

    def to_dict(self):
        return {
            'current_time': self.current_time.strftime('%Y%m%d%H%M%S'),
            'strategy': self.strategy.to_dict() if self.strategy else {},
            'decision': self.decision,
            'account_summary': self.account_summary,
        }