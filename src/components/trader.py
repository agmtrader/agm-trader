from ib_insync import *
from src.utils.logger import logger 
import pandas as pd
import threading
import nest_asyncio
from datetime import datetime
import time
from src.components.strategy import IchimokuBase, SMACrossover
from src.lib.params import IchimokuBaseParams, SMACrossoverParams
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

            self.trading_thread = threading.Thread(target=self.run, args=('SMACROS',))
            self.trading_thread.start()
            nest_asyncio.apply()

        except Exception as e:
            logger.error(f"Error starting trading thread: {str(e)}")
            raise Exception(f"Error starting trading thread: {str(e)}")

    def run(self, strategy_name: str):

        if strategy_name == 'ICHIMOKU_BASE':
            self.strategy = IchimokuBase(IchimokuBaseParams())
        elif strategy_name == 'SMACROS':
            self.strategy = SMACrossover(SMACrossoverParams())
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
        logger.announcement("Executing backtest...", 'info')
        snapshots = []

        contracts = self.strategy.params.contracts
        if len(contracts) == 0:
            logger.error("No contracts found in params for backtest")
            return snapshots

        primary_contract_data = contracts[0]
        secondary_contract_data = contracts[1] if len(contracts) > 1 else None

        if not primary_contract_data.has_data():
            logger.error("Insufficient historical data for backtest")
            return snapshots

        full_primary = primary_contract_data.data
        full_secondary = secondary_contract_data.data if secondary_contract_data and secondary_contract_data.has_data() else full_primary
        n = min(len(full_primary), len(full_secondary))
        if n < 22:  # Minimum for indicators
            logger.warning("Not enough data points for meaningful backtest")
            return snapshots

        # Initialize backtest state
        position = 0
        avg_cost = 0.0
        cum_pnl = 0.0
        portfolio_value = 0.0  # tracks realised + unrealised
        prev_portfolio_value = 0.0
        initial_portfolio_value = None
        cumulative_returns = 0.0
        pending_brackets = []
        active_orders = []

        for i in range(21, n):
            mes_up_to = full_primary[:i+1]
            mym_up_to = full_secondary[:i+1]
            current_mes = mes_up_to[-1]
            prev_mes = mes_up_to[-2] if len(mes_up_to) > 1 else {'close': 0}

            # Create fresh params for this bar
            params = IchimokuBaseParams()
            params.contracts[0].data = mes_up_to
            params.contracts[1].data = mym_up_to

            # Set simulated positions
            if position != 0:
                params.positions = [{
                    'account': 'backtest',
                    'contract': {
                        'symbol': 'MES',
                        'secType': 'FUT',
                        'exchange': 'CME',
                        'currency': 'USD',
                    },
                    'position': position,
                    'avgCost': avg_cost,
                }]
            else:
                params.positions = []

            # Executed orders will be updated if fills occur
            params.executed_orders = []

            # Create strategy instance for this bar
            strategy = IchimokuBase(params)

            # Run strategy to get decision
            decision = strategy.run()

            pnl_this_bar = 0.0  # realised P/L for this bar
            entry_price_this = ''
            exit_price_this = ''

            # Handle decision
            if decision in ['LONG', 'SHORT']:
                orders = strategy.create_orders(decision)
                if orders:
                    pending_brackets.append({'parent': orders[0], 'children': orders[1:]})

            elif decision == 'EXIT':
                if position != 0:
                    fill_price = current_mes['close']
                    action = 'SELL' if position > 0 else 'BUY'
                    qty = abs(position)
                    signed_fill = qty if action == 'BUY' else -qty
                    pnl_this_bar += (fill_price - avg_cost) * (-signed_fill)
                    position = 0
                    avg_cost = 0.0
                    active_orders = []
                    pending_brackets = []
                    exit_price_this = fill_price

            # Simulate fills on this bar
            entry_filled_this_bar = False

            # Check pending brackets (entry orders)
            for bracket in pending_brackets[:]:
                parent = bracket['parent']
                fill_condition = False
                fill_price = parent.lmtPrice

                if parent.action == 'BUY':
                    if current_mes['low'] <= parent.lmtPrice:
                        fill_condition = True
                elif parent.action == 'SELL':
                    if current_mes['high'] >= parent.lmtPrice:
                        fill_condition = True

                if fill_condition:
                    signed_fill = parent.totalQuantity if parent.action == 'BUY' else -parent.totalQuantity
                    is_reducing = (position != 0) and (signed_fill * position < 0)
                    if is_reducing:
                        pnl_this_bar += (fill_price - avg_cost) * (-signed_fill)
                    old_pos = position
                    position += signed_fill
                    if not is_reducing:
                        if old_pos == 0:
                            avg_cost = fill_price
                        else:
                            avg_cost = (abs(old_pos) * avg_cost + abs(signed_fill) * fill_price) / abs(position)
                    else:
                        if position == 0:
                            avg_cost = 0.0

                    # Simulate executed order
                    executed_dict = {
                        'contract': {'symbol': 'MES', 'secType': 'FUT', 'exchange': 'CME', 'currency': 'USD'},
                        'orderStatus': {'filled': parent.totalQuantity, 'remaining': 0, 'avgFillPrice': fill_price},
                        'isActive': False,
                        'isDone': True,
                        'filled': parent.totalQuantity,
                        'remaining': 0,
                    }
                    params.executed_orders.append(executed_dict)

                    # Activate children
                    active_orders.extend(bracket['children'])

                    # Remove from pending
                    pending_brackets.remove(bracket)

                    entry_filled_this_bar = True
                    entry_price_this = fill_price

            # Check active orders (SL and TP)
            for order in active_orders[:]:
                fill_condition = False
                if order.orderType == 'LMT':
                    fill_price = order.lmtPrice
                    if order.action == 'BUY':
                        if current_mes['low'] <= order.lmtPrice:
                            fill_condition = True
                    elif order.action == 'SELL':
                        if current_mes['high'] >= order.lmtPrice:
                            fill_condition = True
                elif order.orderType == 'STP':
                    fill_price = order.auxPrice
                    if order.action == 'BUY':
                        if current_mes['high'] >= order.auxPrice:
                            fill_condition = True
                    elif order.action == 'SELL':
                        if current_mes['low'] <= order.auxPrice:
                            fill_condition = True

                if fill_condition:
                    signed_fill = order.totalQuantity if order.action == 'BUY' else -order.totalQuantity
                    # Assuming these are always reducing
                    pnl_this_bar += (fill_price - avg_cost) * (-signed_fill)
                    position += signed_fill
                    if position == 0:
                        avg_cost = 0.0
                    active_orders.remove(order)

                    # Simulate executed
                    executed_dict = {
                        'contract': {'symbol': 'MES', 'secType': 'FUT', 'exchange': 'CME', 'currency': 'USD'},
                        'orderStatus': {'filled': order.totalQuantity, 'remaining': 0, 'avgFillPrice': fill_price},
                        'isActive': False,
                        'isDone': True,
                        'filled': order.totalQuantity,
                        'remaining': 0,
                    }
                    params.executed_orders.append(executed_dict)

                    exit_price_this = fill_price

            # Check entry candle validation if entry filled this bar
            if entry_filled_this_bar and params.executed_orders:
                strategy.params = params  # Update params with executed orders
                if strategy._check_entry_candle_validation(mes_up_to, mym_up_to, strategy.params.contracts[0].indicators['psar'][-1], strategy.params.contracts[1].indicators['psar'][-1]):
                    logger.info(f"Backtest: Entry validation failed on {current_mes['date']}, exiting at close")
                    if position != 0:
                        fill_price = current_mes['close']
                        action = 'SELL' if position > 0 else 'BUY'
                        qty = abs(position)
                        signed_fill = qty if action == 'BUY' else -qty
                        pnl_this_bar += (fill_price - avg_cost) * (-signed_fill)
                        position = 0
                        avg_cost = 0.0
                        active_orders = []
                        exit_price_this = fill_price

            # Update cumulative PNL (realised)
            cum_pnl += pnl_this_bar

            # Calculate unrealised P/L on any open position
            unrealised = (current_mes['close'] - avg_cost) * position if position != 0 else 0.0

            # Update portfolio value (starting at 0) = realised + unrealised
            portfolio_value = cum_pnl + unrealised

            # Calculate returns based on previous portfolio value
            bar_returns = 0.0
            if prev_portfolio_value != 0:
                bar_returns = (portfolio_value - prev_portfolio_value) / prev_portfolio_value

            # Update for next iteration
            prev_portfolio_value = portfolio_value

            # Track cumulative returns relative to the first non-zero portfolio value
            if initial_portfolio_value is None and portfolio_value != 0:
                initial_portfolio_value = portfolio_value

            if initial_portfolio_value is not None and initial_portfolio_value != 0:
                cumulative_returns = (portfolio_value - initial_portfolio_value) / initial_portfolio_value

            # Create snapshot
            snapshot_dict = {
                'Date': current_mes['date'],
                'Open': current_mes['open'],
                'High': current_mes['high'],
                'Low': current_mes['low'],
                'Close': current_mes['close'],
                'Prev Close': prev_mes['close'],
                'Decision': decision,
                'Position': position,
                'Portfolio Value': portfolio_value,
                'Returns': bar_returns,
                'Cumulative Returns': cumulative_returns,
            }
            snapshots.append(BacktestSnapshot(snapshot_dict))

        # Convert to DataFrame for analysis or logging if needed
        backtest_df = pd.DataFrame([s.to_dict() for s in snapshots])
        backtest_df.to_csv('backtest.csv', index=False)
        logger.announcement(f"Backtest completed with {len(snapshots)} snapshots", 'success')

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