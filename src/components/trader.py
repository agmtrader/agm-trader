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
from src.lib.backtest import BacktestSnapshot

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

    def execute_backtest(self):
        snapshots = []
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