from ib_insync import *
from src.utils.logger import logger
import threading
import asyncio
import nest_asyncio
from queue import Queue
import os
from datetime import datetime
import time
import math
import json
import pandas as pd

from src.components.strategy import IchimokuBase
from src.lib.params import IchimokuBaseParams, ContractData

SLEEP_TIME = 86400
CONNECTION_CHECK_INTERVAL = 30  # Check connection every 30 seconds
MAX_RECONNECT_ATTEMPTS = 5

class Trader:

    def __init__(self):
        self.ib = IB()
        self._loop = None
        self._thread = None
        self._queue = Queue()

        self.running = False
        self.strategy = None
        self.decision = None
        self.account_summary = None
        self.backtest = []  # Array to store backtest snapshots
        self.last_connection_check = time.time()
        self.reconnect_attempts = 0
        self.connection_monitor_thread = None
        self.connection_monitor_running = False

        self.host = os.getenv('IBKR_HOST', None)
        self.port = int(os.getenv('IBKR_PORT', None))

        self.connect()

        try:
            # Start connection monitoring thread
            self.start_connection_monitor()

            self.trading_thread = threading.Thread(target=self.run_strategy, args=('ICHIMOKU_BASE',))
            self.trading_thread.start()
            nest_asyncio.apply()

        except Exception as e:
            logger.error(f"Error starting trading thread: {str(e)}")
            raise Exception(f"Error starting trading thread: {str(e)}")

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _start_event_loop(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self._thread.start()

    def _execute(self, func):
        if self._loop is None:
            self._start_event_loop()
        future = asyncio.run_coroutine_threadsafe(func, self._loop)
        return future.result()

    def is_connected(self):
        """Check if we're currently connected to IBKR"""
        try:
            return self.ib.isConnected()
        except Exception as e:
            logger.error(f"Error checking connection status: {str(e)}")
            return False

    def start_connection_monitor(self):
        """Start the connection monitoring thread"""
        if not self.connection_monitor_running:
            self.connection_monitor_running = True
            self.connection_monitor_thread = threading.Thread(target=self._connection_monitor_worker, daemon=True)
            self.connection_monitor_thread.start()
            logger.announcement("Connection monitor thread started", 'info')

    def stop_connection_monitor(self):
        """Stop the connection monitoring thread"""
        self.connection_monitor_running = False
        if self.connection_monitor_thread and self.connection_monitor_thread.is_alive():
            self.connection_monitor_thread.join(timeout=5)
            logger.info("Connection monitor thread stopped")

    def _connection_monitor_worker(self):
        """Background worker that continuously monitors the connection"""
        logger.info("Connection monitor worker started")
        
        while self.connection_monitor_running:
            logger.info("Checking IBKR connection...")
            try:
                # Check connection status
                if not self.is_connected():
                    logger.warning("Connection monitor detected lost connection. Attempting to reconnect...")
                    self.reconnect()
                else:
                    # Reset reconnect attempts counter on successful connection check
                    if self.reconnect_attempts > 0:
                        logger.info("Connection monitor confirmed connection is restored")
                        self.reconnect_attempts = 0
                
                # Update last connection check time
                self.last_connection_check = time.time()
                
            except Exception as e:
                logger.error(f"Error in connection monitor: {str(e)}")
            
            # Sleep for the check interval
            logger.success(f"Successfully connected to IBKR")
            time.sleep(CONNECTION_CHECK_INTERVAL)
        
        logger.info("Connection monitor worker stopped")

    def reconnect(self):
        """Attempt to reconnect to IBKR with retry logic"""
        self.reconnect_attempts += 1
        
        if self.reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
            logger.error(f"Maximum reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded. Manual intervention required.")
            self.running = False
            return False
            
        logger.info(f"Reconnection attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}")
        
        try:
            # First try to disconnect cleanly if still connected
            if self.ib.isConnected():
                try:
                    async def _disconnect():
                        self.ib.disconnect()
                    self._execute(_disconnect())
                except Exception as e:
                    logger.warning(f"Error during disconnect: {str(e)}")
            
            # Wait a bit before reconnecting
            time.sleep(2)
            
            # Attempt to reconnect
            if self.connect():
                logger.announcement(f"Successfully reconnected to IBKR on attempt {self.reconnect_attempts}", 'success')
                self.reconnect_attempts = 0
                return True
            else:
                logger.error(f"Reconnection attempt {self.reconnect_attempts} failed")
                return False
                
        except Exception as e:
            logger.error(f"Error during reconnection attempt {self.reconnect_attempts}: {str(e)}")
            return False

    def connect(self):
        logger.announcement("Connecting to IBKR...", 'info')
        try:
            async def _connect():
                max_attempts = 3
                attempt = 0
                
                while attempt < max_attempts:
                    try:
                        await self.ib.connectAsync(self.host, self.port, clientId=1)
                        if self.ib.isConnected():
                            return True
                    except Exception as e:
                        logger.error(f"Connection attempt {attempt + 1} failed: {str(e)}")
                        attempt += 1
                        if attempt < max_attempts:
                            logger.info("Waiting before retry...")
                            time.sleep(5)
                
                return False
            
            connected = self._execute(_connect())
            if connected:
                logger.announcement("Connected to IBKR.", 'success')
                self.reconnect_attempts = 0  # Reset counter on successful connection
            else:
                logger.error("Failed to connect to IBKR after multiple attempts")
            return connected
        except Exception as e:
            logger.error(f"Error connecting to IB: {str(e)}")
            return False

    def disconnect(self):
        logger.info("Disconnecting from IBKR")
        
        # Stop the connection monitor first
        self.stop_connection_monitor()
        
        if self.ib.isConnected():
            try:
                async def _disconnect():
                    self.ib.disconnect()
                
                self._execute(_disconnect())
                
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                    self._thread = None
                    self._loop = None
                
                logger.announcement("Disconnected from IBKR", 'success')
                return True
            except Exception as e:
                logger.error(f"Error disconnecting from IB: {str(e)}")
                return False
        return False

    # Strategy
    def run_strategy(self, strategy_name: str):

        if strategy_name == 'ICHIMOKU_BASE':
            strategy = IchimokuBase(IchimokuBaseParams())
            self.strategy = strategy
        else:
            raise Exception(f"Strategy {strategy_name} not found")
        
        # Populate initial strategy params with full historical data
        logger.announcement("Populating initial strategy params...", 'info')
        for contract_data in strategy.params.contracts:
            historical_data = self.get_historical_data(contract_data.contract)
            contract_data.data = historical_data

        # Run backtest first
        self.run_backtest(strategy_name)
        #self.close_all_positions()

        logger.announcement(f"Running strategy: {strategy.name}", 'info')
        
        self.running = True
        
        try:
            while True:

                if not self.running:
                    # Stop connection monitor when exiting
                    self.stop_connection_monitor()
                    exit()

                # Simple connection check - the dedicated monitor thread handles reconnection
                if not self.is_connected():
                    logger.warning("Connection not available for trading. Monitor thread should be handling reconnection...")
                    time.sleep(SLEEP_TIME)
                    continue

                logger.announcement("Populating strategy params...", 'info')

                for contract_data in strategy.params.contracts:
                    historical_data = self.get_historical_data(contract_data.contract)
                    contract_data.data = historical_data
                    
                self.account_summary = self.get_account_summary()
                strategy.params.open_orders = self.get_open_orders()
                strategy.params.executed_orders = self.get_completed_orders()
                strategy.params.positions = self.get_positions()

                # Run strategy
                self.decision = strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                # Store decision in database

                # Handle exit signals
                if self.decision == 'EXIT':
                    logger.warning("EXIT signal received - closing all positions")
                    # Check connection before closing positions
                    if self.is_connected() or self.reconnect():
                        self.close_all_positions()
                    # Clear MYM simulation data when exiting
                    if hasattr(strategy, '_clear_mym_simulation'):
                        strategy._clear_mym_simulation()
                    continue

                # Create orders for the strategy and place them
                order = strategy.create_order(self.decision)
                if order:
                    logger.info("Order created.")
                    # Check connection before placing order
                    if self.is_connected():
                        # TODO: Uncomment the line below when ready for live trading
                        # self.place_order(order)
                        logger.warning("Order placement is currently disabled for safety")
                    else:
                        logger.error("Cannot place order - no connection to IBKR")
                else:
                    logger.info("No order to place for this decision")

                # Update strategy params once more
                logger.announcement("Refreshing strategy params...", 'info')
                
                # Ensure connection before final API calls
                if self.is_connected():
                    strategy.params.open_orders = self.get_open_orders()
                    strategy.params.executed_orders = self.get_completed_orders()
                    strategy.params.positions = self.get_positions()
                else:
                    logger.warning("Skipping final parameter refresh due to connection issues")
                
                # Wait before running the strategy again
                time.sleep(SLEEP_TIME)
                
        except Exception as e:
            logger.error(f"Error running strategy: {str(e)}")
            # Stop connection monitor on error
            self.stop_connection_monitor()
            raise Exception(f"Error running strategy: {str(e)}")

    def run_backtest(self, strategy_name: str):
        """
        Run backtest using historical data from strategy params
        """

        rolling = True
        
        logger.announcement(f"Starting backtest for strategy: {strategy_name}", 'info')
        
        if not self.strategy:
            logger.error("No strategy loaded for backtesting")
            return
        
        # Get the primary contract data (assuming MES is the main one)
        primary_contract_data = None
        for contract_data in self.strategy.params.contracts:
            if contract_data.data and len(contract_data.data) > 0:
                primary_contract_data = contract_data
                break
        
        if not primary_contract_data or not primary_contract_data.data:
            logger.error("No historical data available for backtesting")
            return
        
        historical_data = primary_contract_data.data
        logger.info(f"Running backtest on {len(historical_data)} data points")
        
        # Clear previous backtest results
        self.backtest = []
        
        # We need at least enough data points for the strategy to calculate indicators
        # For Ichimoku, we typically need at least 26 periods
        min_periods = 26
        
        if len(historical_data) < min_periods:
            logger.warning(f"Not enough historical data for backtesting. Need at least {min_periods} periods, got {len(historical_data)}")
            return
        
        try:
            # Iterate through historical data starting from min_periods
            for i in range(min_periods, len(historical_data)):
                current_date = historical_data[i]['date']
                
                # Create a subset of data up to current point for strategy calculation
                subset_data = historical_data[:i+1]
                
                # Temporarily store original data and update with subset
                original_data = {}
                for contract_data in self.strategy.params.contracts:
                    if contract_data.data:
                        # Store original data
                        original_data[id(contract_data)] = contract_data.data
                        # Update with subset for strategy calculation
                        contract_data.data = subset_data
                
                # Clear live trading data for clean backtest
                self.strategy.params.open_orders = []
                self.strategy.params.executed_orders = []
                self.strategy.params.positions = []
                
                # Run strategy with current data subset
                decision = self.strategy.run()
                self.decision = decision
                
                # Create backtest snapshot
                snapshot = BacktestSnapshot(self, current_date, historical_data[i])
                self.backtest.append(snapshot)
                
                # Restore original data after strategy calculation
                for contract_data in self.strategy.params.contracts:
                    if id(contract_data) in original_data:
                        contract_data.data = original_data[id(contract_data)]
                
                # Log progress every 50 data points
                if i % 50 == 0:
                    logger.info(f"Backtest progress: {i}/{len(historical_data)} ({(i/len(historical_data)*100):.1f}%)")
            
            logger.announcement(f"Backtest completed. Generated {len(self.backtest)} snapshots", 'success')
                    
        except Exception as e:
            logger.error(f"Error during backtesting: {str(e)}")
            raise Exception(f"Error during backtesting: {str(e)}")

    # IBKR
    def get_historical_data(self, contract: Contract):
        logger.info(f"Getting historical data for {contract.symbol}...")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting historical data. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get historical data - no connection to IBKR")
        
        try:
            async def _get_historical_data():
                historical_data_response = self.ib.reqHistoricalData(contract, endDateTime='', durationStr='1 Y', barSizeSetting='1 day', whatToShow='TRADES', useRTH=1)
                historical_data = []
                for bar in historical_data_response:
                    historical_data.append(bar.dict())
                
                return historical_data
            
            historical_data = self._execute(_get_historical_data())
            logger.success(f"Successfully got historical data.")
            return historical_data
        except Exception as e:
            logger.error(f"Error getting historical data: {str(e)}")
            # Try to reconnect and retry once
            if self.reconnect():
                try:
                    historical_data = self._execute(_get_historical_data())
                    logger.success(f"Successfully got historical data after reconnection.")
                    return historical_data
                except Exception as retry_e:
                    logger.error(f"Error getting historical data after reconnection: {str(retry_e)}")
            raise Exception(f"Error getting historical data: {str(e)}")

    def get_latest_price(self, contract: Contract):
        logger.info(f"Getting latest price")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting latest price. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get latest price - no connection to IBKR")
        
        try:
            async def _get_latest_price():
                self.ib.reqMarketDataType(3)
                market_data_response = self.ib.reqMktData(contract, '233', False, False, [])
                while math.isnan(market_data_response.last):
                    self.ib.sleep(0.05)
                    logger.info(f"Waiting for market data...")
                return market_data_response.last
            
            latest_price = self._execute(_get_latest_price())
            logger.success(f"Successfully got latest price.")
            return latest_price
        except Exception as e:
            logger.error(f"Error getting latest price: {str(e)}")
            raise Exception(f"Error getting latest price: {str(e)}")

    def get_account_summary(self):
        logger.info("Getting account summary")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting account summary. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get account summary - no connection to IBKR")
        
        try:
            async def _get_account_summary():
                account_summary_response = self.ib.accountSummary()
                account_summary = []
                for summary in account_summary_response:
                    account_summary_dict = {}
                    account_summary_dict['account'] = summary.account
                    account_summary_dict['tag'] = summary.tag
                    account_summary_dict['value'] = summary.value
                    account_summary_dict['currency'] = summary.currency
                    account_summary_dict['modelCode'] = summary.modelCode
                    account_summary.append(account_summary_dict)
                return account_summary
            account_summary = self._execute(_get_account_summary())
            logger.success(f"Successfully got account summary.")
            return account_summary
        except Exception as e:
            logger.error(f"Error getting account summary: {str(e)}")
            raise Exception(f"Error getting account summary: {str(e)}")

    def get_positions(self):
        logger.info("Getting positions")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting positions. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get positions - no connection to IBKR")
        
        try:
            async def _get_positions():
                positions_response = self.ib.positions()
                positions = []
                for position in positions_response:
                    position_dict = {
                        'account': position.account,
                        'contract': {
                            'symbol': position.contract.symbol,
                            'secType': position.contract.secType,
                            'exchange': position.contract.exchange,
                            'currency': getattr(position.contract, 'currency', 'USD'),
                        },
                        'position': position.position,
                        'avgCost': position.avgCost,
                    }
                    positions.append(position_dict)
                logger.success(f"Successfully got {len(positions)} positions.")
                return positions
            
            positions = self._execute(_get_positions())
            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            raise Exception(f"Error getting positions: {str(e)}")

    def get_completed_orders(self):
        logger.info("Getting completed orders")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting completed orders. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get completed orders - no connection to IBKR")
        
        try:
            async def _get_completed_orders():
                orders_response = self.ib.reqCompletedOrders(False)
                orders = []
                for order in orders_response:
                    orders.append({
                        'contract': {
                            'symbol': order.contract.symbol,
                            'secType': order.contract.secType,
                            'exchange': order.contract.exchange,
                            'currency': getattr(order.contract, 'currency', 'USD'),
                        },
                        'orderStatus': {
                            'orderId': order.orderStatus.orderId,
                            'status': order.orderStatus.status,
                            'filled': order.orderStatus.filled,
                            'remaining': order.orderStatus.remaining,
                            'avgFillPrice': order.orderStatus.avgFillPrice,
                        },
                        'isActive': order.isActive(),
                        'isDone': order.isDone(),
                        'filled': order.filled(),
                        'remaining': order.remaining(),
                    })
                logger.success(f"Successfully got {len(orders)} completed orders.")
                return orders
            
            completed_orders = self._execute(_get_completed_orders())
            return completed_orders
        except Exception as e:
            logger.error(f"Error getting completed orders: {str(e)}")
            raise Exception(f"Error getting completed orders: {str(e)}")

    def get_open_orders(self):
        logger.info("Getting open orders")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when getting open orders. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot get open orders - no connection to IBKR")
        
        try:
            async def _get_open_orders():
                orders_response = self.ib.openOrders()
                orders = []
                for trade in orders_response:
                    order_dict = {
                        'contract': {
                            'symbol': trade.contract.symbol,
                            'secType': trade.contract.secType,
                            'exchange': trade.contract.exchange,
                            'currency': getattr(trade.contract, 'currency', 'USD'),
                        },
                        'order': {
                            'orderId': trade.order.orderId,
                            'action': trade.order.action,
                            'totalQuantity': trade.order.totalQuantity,
                            'orderType': trade.order.orderType,
                            'lmtPrice': getattr(trade.order, 'lmtPrice', 0),
                            'auxPrice': getattr(trade.order, 'auxPrice', 0),
                        },
                        'orderStatus': {
                            'status': trade.orderStatus.status,
                            'filled': trade.orderStatus.filled,
                            'remaining': trade.orderStatus.remaining,
                            'avgFillPrice': trade.orderStatus.avgFillPrice,
                        }
                    }
                    orders.append(order_dict)
                logger.success(f"Successfully got {len(orders)} open orders.")
                return orders
            
            open_orders = self._execute(_get_open_orders())
            return open_orders
        except Exception as e:
            logger.error(f"Error getting open orders: {str(e)}")
            raise Exception(f"Error getting open orders: {str(e)}")

    def place_order(self, order: Order):
        logger.info(f"Placing order: {order}")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when placing order. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot place order - no connection to IBKR")
        
        try:
            async def _place_order():

                # Get the first contract from strategy params
                mes_data = self.strategy.params.get_mes_data()
                if not mes_data:
                    logger.error("No MES contract data found for order placement")
                    return False
                contract = mes_data.contract
                self.ib.qualifyContracts(contract)

                for o in order:
                    print(o)
                    self.ib.placeOrder(contract, o)

                return True
            
            self._execute(_place_order())
            return True
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            raise Exception(f"Error placing order: {str(e)}")
        
    def close_all_positions(self):
        logger.info("Closing all positions")
        
        # Check connection before making API call
        if not self.is_connected():
            logger.warning("No connection when closing positions. Attempting reconnection...")
            if not self.reconnect():
                raise Exception("Cannot close positions - no connection to IBKR")
        
        try:
            async def _close_all_positions():
                for order in self.ib.orders():
                    self.ib.cancelOrder(order)
                logger.success("Successfully closed all positions")
                return True
            
            self._execute(_close_all_positions())
            return True
        except Exception as e:
            logger.error(f"Error closing all positions: {str(e)}")
            raise Exception(f"Error closing all positions: {str(e)}")

class BacktestSnapshot:
    def __init__(self, trader: Trader, current_date, market_data):
        self.current_time = current_date
        self.decision = trader.decision
        self.market_data = market_data  # OHLCV data for this period
        self.trader = trader  # Store trader reference
        self.strategy_indicators = self.get_strategy_indicators(trader.strategy) if trader.strategy else {}
        
    def get_strategy_indicators(self, strategy):
        """
        Extract relevant indicators from the strategy for analysis
        """
        indicators = {}
        
        # If it's an Ichimoku strategy, get the indicator values from params
        if hasattr(strategy, 'params'):
            indicators = {
                'tenkan': getattr(strategy.params, 'tenkan', None),
                'kijun': getattr(strategy.params, 'kijun', None),
                'psar_mes': getattr(strategy.params, 'psar_mes', [])[-1] if getattr(strategy.params, 'psar_mes', []) else None,
                'psar_mym': getattr(strategy.params, 'psar_mym', [])[-1] if getattr(strategy.params, 'psar_mym', []) else None,
                'number_of_contracts': getattr(strategy.params, 'number_of_contracts', None),
                'psar_difference': getattr(strategy.params, 'psar_difference', None),
            }
        
        return indicators

    def to_dict(self):
        return {
            'current_time': self.current_time.strftime('%Y%m%d%H%M%S') if isinstance(self.current_time, datetime) else str(self.current_time),
            'decision': self.decision,
            'market_data': {
                'open': self.market_data.get('open', 0),
                'high': self.market_data.get('high', 0),
                'low': self.market_data.get('low', 0),
                'close': self.market_data.get('close', 0),
                'volume': self.market_data.get('volume', 0),
            } if self.market_data else {},
            'strategy_indicators': self.strategy_indicators,
        }

class TraderSnapshot:

    def __init__(self, trader: Trader):
        logger.announcement("Creating Trader Snapshot", 'info')
        self.current_time = datetime.now()
        self.strategy = trader.strategy
        self.decision = trader.decision
        self.account_summary = trader.account_summary
        self.backtest = trader.backtest

    def to_dict(self):
        return {
            'current_time': self.current_time.strftime('%Y%m%d%H%M%S'),
            'strategy': self.strategy.to_dict() if self.strategy else {},
            'decision': self.decision,
            'account_summary': self.account_summary,
            'backtest': [snapshot.to_dict() for snapshot in self.backtest] if self.backtest else [],
        }