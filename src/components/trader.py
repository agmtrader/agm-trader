from ib_insync import *
from src.utils.logger import logger 
import threading
import nest_asyncio
from datetime import datetime
import time

from src.components.connection_manager import ConnectionManager
from src.components.data_manager import DataManager
from src.components.order_manager import OrderManager

from src.lib.strategy import IchimokuBase, SMACrossover
from src.lib.params import IchimokuBaseParams, SMACrossoverParams

SLEEP_TIME = 86400

class Trader:

    def __init__(self):
        self.conn = ConnectionManager()
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

            self.trading_thread = threading.Thread(target=self.run, args=('SMACROSSOVER',))
            self.trading_thread.start()
            nest_asyncio.apply()

        except Exception as e:
            logger.error(f"Error starting trading thread: {str(e)}")
            raise Exception(f"Error starting trading thread: {str(e)}")

    def run(self, strategy_name: str):

        match strategy_name:
            case 'ICHIMOKU_BASE':
                self.strategy = IchimokuBase(IchimokuBaseParams())
            case 'SMACROSSOVER':
                self.strategy = SMACrossover(SMACrossoverParams())
            case _:
                raise Exception(f"Strategy {strategy_name} not found")

        self.account_summary = self.data.get_account_summary()
        self.order_mgr.close_all_positions()
        self.strategy.refresh_params(self.data)

        self.backtest = self.strategy.backtest()

        self.running = True
        logger.announcement(f"Running strategy: {self.strategy.name}", 'info')        

        try:
            while True:

                if not self.conn.is_connected():
                    self.conn.reconnect()

                if not self.running:
                    self.conn.stop_connection_monitor()
                    exit()

                self.strategy.refresh_params(self.data)
                self.account_summary = self.data.get_account_summary()
                
                self.decision = self.strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                if self.decision == 'EXIT':
                    self.order_mgr.close_all_positions()

                order = self.strategy.create_orders(self.decision)
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

    def to_dict(self):
        return {
            'current_time': datetime.now().strftime('%Y%m%d%H%M%S'),
            'strategy': self.strategy.to_dict() if self.strategy else {},
            'decision': self.decision,
            'account_summary': self.account_summary,
        }
