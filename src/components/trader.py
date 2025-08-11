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
        Returns array with columns: Date, Open, High, Low, Close, Prev Close, Decision, EntryPrice, ExitPrice, P/L, Cum. P/L
        """
        
        logger.announcement(f"Starting backtest for strategy: {strategy_name}", 'info')
        
        if not self.strategy:
            logger.error("No strategy loaded for backtesting")
            return
        
        # Get the primary contract data (assuming MES is the main one)
        main_contract = self.strategy.params.contracts[0]

        if not main_contract or not main_contract.data:
            logger.error("No historical data available for backtesting")
            return
        
        historical_data = main_contract.data
        logger.info(f"Running backtest on {len(historical_data)} data points")
        
        # Clear previous backtest results
        self.backtest = []
        
        # We need at least enough data points for the strategy to calculate indicators
        # For Ichimoku, we typically need at least 26 periods
        min_periods = 26
        
        if len(historical_data) < min_periods:
            logger.warning(f"Not enough historical data for backtesting. Need at least {min_periods} periods, got {len(historical_data)}")
            return
        
        position = None
        entry_price = 0.0
        quantity = 0
        tp1_price = 0.0
        tp2_price = 0.0
        sl_price = 0.0
        tp1_qty = 0
        tp2_qty = 0
        cumulative_pnl = 0.0
        
        try:
            # Iterate through historical data starting from min_periods
            for i in range(min_periods, len(historical_data)):
                current_candle = historical_data[i]
                prev_candle = historical_data[i-1] if i > 0 else current_candle
                current_date = current_candle['date']
                
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
                
                # Initialize backtest row
                backtest_row = {
                    'Date': current_date,
                    'Open': current_candle['open'],
                    'High': current_candle['high'],
                    'Low': current_candle['low'],
                    'Close': current_candle['close'],
                    'Prev Close': prev_candle['close'],
                    'Decision': decision,
                    'EntryPrice': '',
                    'ExitPrice': '',
                    'P/L': 0.0,
                    'Cum. P/L': cumulative_pnl
                }
                
                # Check for exits first (stop loss, take profit, or strategy exit)
                if position:
                    exit_price = None
                    exit_reason = ''
                    
                    # Check stop loss and take profit levels
                    if position == 'LONG':
                        # For daily data, use close price to determine exits
                        # Check stop loss (close price goes below SL)
                        if current_candle['close'] <= sl_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'SL'
                        # Check TP1 first (smaller target, more likely to hit first)
                        elif tp1_qty > 0 and current_candle['close'] >= tp1_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'TP1'
                        # Check TP2 only if TP1 was already hit (tp1_qty should be 0)
                        elif tp2_qty > 0 and tp1_qty == 0 and current_candle['close'] >= tp2_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'TP2'
                    
                    elif position == 'SHORT':
                        # For daily data, use close price to determine exits
                        # Check stop loss (close price goes above SL)
                        if current_candle['close'] >= sl_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'SL'
                        # Check TP1 first (smaller target, more likely to hit first)
                        elif tp1_qty > 0 and current_candle['close'] <= tp1_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'TP1'
                        # Check TP2 only if TP1 was already hit (tp1_qty should be 0)
                        elif tp2_qty > 0 and tp1_qty == 0 and current_candle['close'] <= tp2_price:
                            exit_price = current_candle['close']  # Use actual close price
                            exit_reason = 'TP2'
                    
                    # Check strategy exit signal
                    if decision == 'EXIT':
                        exit_price = current_candle['close']
                        exit_reason = 'EXIT_SIGNAL'
                        quantity = 0  # Close full position
                    
                    # Process exit if one occurred
                    if exit_price:
                        backtest_row['ExitPrice'] = exit_price
                        
                        # Calculate P/L based on the quantity being closed
                        if exit_reason == 'TP1':
                            exit_qty = tp1_qty
                        elif exit_reason == 'TP2':
                            exit_qty = tp2_qty
                        else:
                            # SL or EXIT_SIGNAL - close full remaining position
                            exit_qty = quantity
                        
                        # Validate exit_price is not infinity or NaN
                        if not (exit_price and exit_price != float('inf') and exit_price != float('-inf') and not math.isnan(exit_price)):
                            logger.error(f"Invalid exit price: {exit_price}, using current close price instead")
                            exit_price = current_candle['close']
                            backtest_row['ExitPrice'] = exit_price
                        
                        # Calculate P/L
                        if position == 'LONG':
                            pnl = (exit_price - entry_price) * exit_qty
                        else:  # SHORT
                            pnl = (entry_price - exit_price) * exit_qty
                        
                        # Validate P/L is not infinity or NaN
                        if math.isnan(pnl) or pnl == float('inf') or pnl == float('-inf'):
                            logger.error(f"Invalid P/L calculated: {pnl}, setting to 0")
                            pnl = 0.0
                        
                        backtest_row['P/L'] = pnl
                        cumulative_pnl += pnl
                        
                        # Validate cumulative P/L
                        if math.isnan(cumulative_pnl) or cumulative_pnl == float('inf') or cumulative_pnl == float('-inf'):
                            logger.error(f"Invalid cumulative P/L: {cumulative_pnl}, resetting to current P/L")
                            cumulative_pnl = pnl
                        
                        backtest_row['Cum. P/L'] = cumulative_pnl
                        backtest_row['Decision'] = f"{decision}_{exit_reason}" if decision not in ['EXIT'] else exit_reason
                        
                        # Update position tracking
                        if exit_reason == 'TP1':
                            # Only reduce TP1 quantity, TP2 remains
                            tp1_qty = 0
                            # Remaining quantity is now just TP2
                            quantity = tp2_qty
                        elif exit_reason == 'TP2':
                            # Close TP2 quantity, only TP1 might remain
                            tp2_qty = 0
                            # If TP1 was already closed, close the position
                            if tp1_qty == 0:
                                quantity = 0
                        else:
                            # Close full position for SL or EXIT
                            quantity = 0
                            tp1_qty = 0
                            tp2_qty = 0
                        
                        # Close position completely if no quantity remains
                        if quantity <= 0 and tp1_qty <= 0 and tp2_qty <= 0:
                            position = None
                            entry_price = 0.0
                            quantity = 0
                            tp1_price = 0.0
                            tp2_price = 0.0
                            sl_price = 0.0
                            tp1_qty = 0
                            tp2_qty = 0
                
                # Check for new entries (only if no position)
                if not position and decision in ['LONG', 'SHORT']:
                    # Use the strategy's create_order method to get proper order details
                    orders = self.strategy.create_order(decision)
                    
                    if orders and len(orders) > 0:
                        # Extract order details from the strategy's orders
                        parent_order = orders[0]  # First order is the entry
                        entry_price = parent_order.lmtPrice
                        quantity = parent_order.totalQuantity
                        
                        # Initialize defaults
                        sl_price = entry_price  # Default fallback
                        tp1_price = entry_price * 1.01 if decision == 'LONG' else entry_price * 0.99  # Default fallback
                        tp2_price = entry_price * 1.02 if decision == 'LONG' else entry_price * 0.98  # Default fallback
                        tp1_qty = 0
                        tp2_qty = 0
                        
                        # Parse child orders based on known structure: [Parent, StopLoss, TP1, TP2]
                        if len(orders) >= 4:
                            # Order 1: Stop Loss (StopOrder)
                            stop_order = orders[1]
                            if hasattr(stop_order, 'stopPrice'):
                                sl_price = stop_order.stopPrice
                                #logger.info(f"Found SL order at {sl_price:.2f}")
                            
                            # Order 2: TP1 (LimitOrder)
                            tp1_order = orders[2]
                            if hasattr(tp1_order, 'lmtPrice'):
                                tp1_price = tp1_order.lmtPrice
                                tp1_qty = tp1_order.totalQuantity
                                #logger.info(f"Found TP1 order at {tp1_price:.2f} for {tp1_qty} contracts")
                            
                            # Order 3: TP2 (LimitOrder)
                            tp2_order = orders[3]
                            if hasattr(tp2_order, 'lmtPrice'):
                                tp2_price = tp2_order.lmtPrice
                                tp2_qty = tp2_order.totalQuantity
                                #logger.info(f"Found TP2 order at {tp2_price:.2f} for {tp2_qty} contracts")
                        else:
                            logger.warning(f"Expected 4 orders but got {len(orders)}, using defaults")
                        
                        # Validate prices are reasonable
                        if not (0 < entry_price < 50000):
                            logger.error(f"Invalid entry price {entry_price}, using current close {current_candle['close']}")
                            entry_price = current_candle['close']
                        
                        if not (0 < sl_price < 50000):
                            logger.error(f"Invalid SL price {sl_price}, using entry price {entry_price}")
                            sl_price = entry_price
                        
                        if not (0 < tp1_price < 50000):
                            logger.error(f"Invalid TP1 price {tp1_price}, using default calculation")
                            tp1_price = entry_price * 1.01 if decision == 'LONG' else entry_price * 0.99
                        
                        if not (0 < tp2_price < 50000):
                            logger.error(f"Invalid TP2 price {tp2_price}, using default calculation")
                            tp2_price = entry_price * 1.02 if decision == 'LONG' else entry_price * 0.98
                        
                        # Set position
                        position = decision
                        backtest_row['EntryPrice'] = entry_price
                        
                        #logger.info(f"{decision} entry at {entry_price:.2f}, TP1: {tp1_price:.2f} ({tp1_qty}), TP2: {tp2_price:.2f} ({tp2_qty}), SL: {sl_price:.2f}")
                    else:
                        logger.warning(f"Strategy returned {decision} but no orders were created")
                
                # Update cumulative P/L in row
                backtest_row['Cum. P/L'] = cumulative_pnl
                
                # Add row to backtest results as BacktestSnapshot object
                self.backtest.append(BacktestSnapshot(backtest_row))
                
                # Restore original data after strategy calculation
                for contract_data in self.strategy.params.contracts:
                    if id(contract_data) in original_data:
                        contract_data.data = original_data[id(contract_data)]

            self.export_backtest_to_csv()
                
            logger.announcement(f"Backtest completed. Generated {len(self.backtest)} rows, Final P/L: {cumulative_pnl:.2f}", 'success')
                    
        except Exception as e:
            logger.error(f"Error during backtesting: {str(e)}")
            raise Exception(f"Error during backtesting: {str(e)}")
        
        return self.backtest

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

    def export_backtest_to_csv(self, filename=None):
        """
        Export backtest results to CSV file
        
        Args:
            filename (str, optional): Custom filename for the CSV. If None, uses timestamp-based name.
        
        Returns:
            str: Path to the exported CSV file
        """
        if not self.backtest or len(self.backtest) == 0:
            logger.error("No backtest data available to export")
            return None
        
        try:
            # Generate filename if not provided
            if filename is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                strategy_name = self.strategy.name if self.strategy else 'unknown_strategy'
                filename = f"backtest_{strategy_name}_{timestamp}.csv"
            
            # Ensure filename ends with .csv
            if not filename.endswith('.csv'):
                filename += '.csv'
            
            # Convert backtest snapshots to list of dictionaries
            backtest_data = []
            for snapshot in self.backtest:
                backtest_data.append(snapshot.to_dict())
            
            # Create DataFrame and export to CSV
            df = pd.DataFrame(backtest_data)
            
            # Ensure proper column order
            column_order = ['Date', 'Open', 'High', 'Low', 'Close', 'Prev Close', 
                          'Decision', 'EntryPrice', 'ExitPrice', 'P/L', 'Cum. P/L']
            
            # Reorder columns if they exist
            existing_columns = [col for col in column_order if col in df.columns]
            df = df[existing_columns]
            
            # Export to CSV
            df.to_csv(filename, index=False)
            
            logger.announcement(f"Backtest data exported to {filename}", 'success')
            logger.info(f"Exported {len(backtest_data)} backtest rows")
            
            # Calculate and log summary statistics
            total_trades = len([s for s in self.backtest if s.has_exit()])
            profitable_trades = len([s for s in self.backtest if s.is_profitable()])
            final_pnl = self.backtest[-1].cumulative_pnl if self.backtest else 0
            
            win_rate = (profitable_trades/total_trades*100) if total_trades > 0 else 0
            logger.info(f"Backtest Summary - Total Trades: {total_trades}, "
                       f"Profitable: {profitable_trades}, "
                       f"Win Rate: {win_rate:.1f}%, "
                       f"Final P/L: {final_pnl:.2f}")
            
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting backtest to CSV: {str(e)}")
            raise Exception(f"Error exporting backtest to CSV: {str(e)}")

class BacktestSnapshot:
    def __init__(self, backtest_row_dict):
        """
        Initialize from the new backtest row dictionary structure
        """
        self.date = backtest_row_dict.get('Date')
        self.open = backtest_row_dict.get('Open', 0)
        self.high = backtest_row_dict.get('High', 0)
        self.low = backtest_row_dict.get('Low', 0)
        self.close = backtest_row_dict.get('Close', 0)
        self.prev_close = backtest_row_dict.get('Prev Close', 0)
        self.decision = backtest_row_dict.get('Decision', 'STAY')
        self.entry_price = backtest_row_dict.get('EntryPrice', '')
        self.exit_price = backtest_row_dict.get('ExitPrice', '')
        self.pnl = backtest_row_dict.get('P/L', 0.0)
        self.cumulative_pnl = backtest_row_dict.get('Cum. P/L', 0.0)

    def to_dict(self):
        """
        Convert back to dictionary format for CSV export or analysis
        """
        return {
            'Date': self.date.strftime('%Y-%m-%d') if hasattr(self.date, 'strftime') else str(self.date),
            'Open': self.open,
            'High': self.high,
            'Low': self.low,
            'Close': self.close,
            'Prev Close': self.prev_close,
            'Decision': self.decision,
            'EntryPrice': self.entry_price,
            'ExitPrice': self.exit_price,
            'P/L': self.pnl,
            'Cum. P/L': self.cumulative_pnl
        }
    
    def has_entry(self):
        """Check if this snapshot contains an entry"""
        return self.entry_price != '' and self.entry_price != 0
    
    def has_exit(self):
        """Check if this snapshot contains an exit"""
        return self.exit_price != '' and self.exit_price != 0
    
    def is_profitable(self):
        """Check if this trade was profitable"""
        return self.pnl > 0 if self.pnl != 0 else False

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