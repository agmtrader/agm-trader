from ib_insync import *
from src.utils.logger import logger 
import threading
import nest_asyncio
from datetime import datetime
import time

import pandas as pd

from src.utils.managers.connection_manager import ConnectionManager
from src.utils.managers.data_manager import DataManager
from src.utils.managers.order_manager import OrderManager

from src.lib.trade_snapshot import TradeSnapshot

from src.components.strategy.sma_cross import SMACrossover, SMACrossoverParams
from src.components.strategy.ichimoku_base import IchimokuBase, IchimokuBaseParams

class Trader:

    def __init__(self):
        
        self.conn = ConnectionManager()
        self.data = DataManager(self.conn)
        self.order_mgr = OrderManager(self.conn)

        self.running = False
        self.strategy = None
        self.decision = None
        self.account_summary = None

        self.trades = []
        self.history = []

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
            case 'SMACROSSOVER':
                self.strategy = SMACrossover(SMACrossoverParams())
            case 'ICHIMOKU_BASE':
                self.strategy = IchimokuBase(IchimokuBaseParams())
            case _:
                raise Exception(f"Strategy {strategy_name} not found")

        self.order_mgr.cancel_all_orders()
        self.order_mgr.close_all_positions()

        self.account_summary = self.data.get_account_summary()
        self.strategy.params = self.strategy.refresh_params(self.data)

        self.trades, decisions = self.strategy.backtest()

        for d in decisions:
            self.history.append({
                'current_time': d.get('date'),
                'strategy': self.strategy.to_dict() if self.strategy else {},
                'decision': d.get('decision'),
                'account_summary': self.account_summary,
            })

        trades_df = pd.DataFrame([trade.to_dict() for trade in self.trades])
        trades_df.to_csv('backtest.csv', index=False)

        self.running = True

        logger.announcement(f"Running strategy: {self.strategy.name}. Running again in {self.strategy.timeframe_seconds/3600} hours", 'info')    

        try:
            while True:

                if not self.conn.is_connected():
                    self.conn.reconnect()

                if not self.running:
                    self.conn.stop_connection_monitor()
                    exit()

                self.strategy.refresh_params(self.data)
                self.strategy.params = self.strategy.refresh_params(self.data)
                self.account_summary = self.data.get_account_summary()
                
                self.decision = self.strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                if self.decision == 'EXIT':
                    self.order_mgr.close_all_positions()

                if self.decision != 'STAY':
                    orders = self.strategy.create_orders(self.decision)
                    logger.info(f"Orders created: {orders}")
                    if orders:
                        for order in orders:
                            self.order_mgr.place_order(self.strategy, order)
                            trade = TradeSnapshot(
                                side=self.decision,
                                qty=order.totalQuantity,
                                entry_date=datetime.now(),
                                entry_price=order.lmtPrice,
                            )
                            self.trades.append(trade)
                            #logger.warning("Order placement is currently disabled for safety")
                            logger.announcement(f"Order placed: {order}", 'success')
                    
                # Refresh strategy params
                self.account_summary = self.data.get_account_summary()
                self.strategy.refresh_params(self.data)
                self.strategy.params = self.strategy.refresh_params(self.data)

                # Record a snapshot of the current state every timeframe
                self.history.append(self.to_dict())

                time.sleep(self.strategy.timeframe_seconds)
                
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