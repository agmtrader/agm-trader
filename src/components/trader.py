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
            self.trading_thread = threading.Thread(target=self.run, args=('ICHIMOKU_BASE',))
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

        # Record a history of strategy decisions and prices
        for d in decisions:
            self.history.append({
                'current_time': d.get('date'),
                'strategy': self.strategy.to_dict() if self.strategy else {},
                'decision': d.get('decision'),
                'account_summary': self.account_summary,
            })

        self.running = True

        logger.announcement(f"Running strategy: {self.strategy.name}. Running again in {self.strategy.timeframe_seconds/3600} hours", 'info')    

        try:
            while True:

                if not self.running:
                    self.conn.stop_connection_monitor()
                    exit()

                if not self.conn.is_connected():
                    self.conn.reconnect()
                    continue
                    
                self.strategy.params = self.strategy.refresh_params(self.data)
                self.account_summary = self.data.get_account_summary()
                
                self.decision = self.strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                if self.decision == 'EXIT':
                    self.order_mgr.close_all_positions()

                if self.decision != 'STAY' and self.decision != 'EXIT':
                    orders = self.strategy.create_orders(self.decision)
                    logger.info(f"Orders created: {orders}")
                    if orders:
                        for order in orders:
                            self.order_mgr.place_order(self.strategy, order)
                            # We no longer create and store a TradeSnapshot for every order entry.
                            # Snapshots should be registered only when a position is closed (EXIT)
                            # or when a take-profit / partial exit is executed.
                            logger.announcement(f"Order placed: {order}", 'success')

                        # Record snapshots only for exits / partial exits
                        if self.decision == 'EXIT' or self.decision.startswith('PARTIAL_EXIT_'):
                            for order in orders:
                                # Use order's limit/stop price when available; otherwise fallback to 0
                                price = getattr(order, 'lmtPrice', None) or getattr(order, 'stopPrice', None) or 0
                                snap = TradeSnapshot(
                                    side=self.decision,
                                    qty=order.totalQuantity,
                                    entry_date=datetime.now(),
                                    entry_price=price,
                                )
                                self.trades.append(snap)
                            logger.info(f"Trade snapshots registered for {self.decision}")
                    
                # Refresh strategy params
                self.account_summary = self.data.get_account_summary()
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