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

SLEEP_TIME = 60

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

        self.host = os.getenv('IBKR_HOST', None)
        self.port = int(os.getenv('IBKR_PORT', None))

        self.connect()

        try:

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

    def connect(self):
        logger.announcement("Connecting to IBKR...", 'info')
        try:
            async def _connect():
                while True:
                    try:
                        await self.ib.connectAsync(self.host, self.port, clientId=1)
                        if self.ib.isConnected():
                            return True
                    except Exception as e:
                        logger.error(f"Error connecting to IB: {str(e)}")
                    logger.info("Waiting for connection...")
                    time.sleep(5)
            
            connected = self._execute(_connect())
            if connected:
                logger.announcement("Connected to IBKR.", 'success')
            return connected
        except Exception as e:
            logger.error(f"Error connecting to IB: {str(e)}")
            raise Exception(f"Error connecting to IB: {str(e)}")
        
    def disconnect(self):
        logger.info("Disconnecting from IBKR")
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
                    exit()

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
                    self.close_all_positions()
                    # Clear MYM simulation data when exiting
                    if hasattr(strategy, '_clear_mym_simulation'):
                        strategy._clear_mym_simulation()
                    continue

                # Create orders for the strategy and place them
                order = strategy.create_order(self.decision)
                if order:
                    logger.info("Order created.")
                    # TODO: Uncomment the line below when ready for live trading
                    # self.place_order(order)
                    logger.warning("Order placement is currently disabled for safety")
                else:
                    logger.info("No order to place for this decision")

                # Update strategy params once more
                logger.announcement("Refreshing strategy params...", 'info')
                strategy.params.open_orders = self.get_open_orders()
                strategy.params.executed_orders = self.get_completed_orders()
                strategy.params.positions = self.get_positions()
                
                # Wait before running the strategy again
                time.sleep(SLEEP_TIME)
                
        except Exception as e:
            logger.error(f"Error running strategy: {str(e)}")
            raise Exception(f"Error running strategy: {str(e)}")

    def run_backtest(self, strategy_name: str):
        """
        Run backtest using historical data from strategy params
        """
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
    
    def get_backtest_summary(self):
        """
        Generate a summary of backtest results
        """
        if not self.backtest:
            return {"error": "No backtest data available"}
        
        total_signals = len(self.backtest)
        buy_signals = len([s for s in self.backtest if s.decision == 'BUY'])
        sell_signals = len([s for s in self.backtest if s.decision == 'SELL'])
        hold_signals = len([s for s in self.backtest if s.decision == 'HOLD'])
        
        return {
            "total_periods": total_signals,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "hold_signals": hold_signals,
            "buy_percentage": (buy_signals / total_signals * 100) if total_signals > 0 else 0,
            "sell_percentage": (sell_signals / total_signals * 100) if total_signals > 0 else 0,
            "hold_percentage": (hold_signals / total_signals * 100) if total_signals > 0 else 0,
            "start_date": self.backtest[0].current_time if self.backtest else None,
            "end_date": self.backtest[-1].current_time if self.backtest else None,
        }

    def export_backtest_results(self, filename=None):
        """
        Export backtest results to JSON file
        """
        if not self.backtest:
            logger.warning("No backtest data to export")
            return False
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"backtest_results_{timestamp}.json"
        
        try:
            # Convert all snapshots to dict format
            backtest_data = {
                "summary": self.get_backtest_summary(),
                "snapshots": [snapshot.to_dict() for snapshot in self.backtest]
            }
            
            # Create backtest directory if it doesn't exist
            os.makedirs("backtest_results", exist_ok=True)
            filepath = os.path.join("backtest_results", filename)
            
            with open(filepath, 'w') as f:
                json.dump(backtest_data, f, indent=2)
            
            logger.announcement(f"Backtest results exported to {filepath}", 'success')
            return filepath
            
        except Exception as e:
            logger.error(f"Error exporting backtest results: {str(e)}")
            return False

    def get_backtest_dataframe(self):
        """
        Convert backtest results to pandas DataFrame for analysis
        """
        if not self.backtest:
            logger.warning("No backtest data available")
            return None
        
        try:
            data = []
            for snapshot in self.backtest:
                row = {
                    'date': snapshot.current_time,
                    'decision': snapshot.decision,
                    'open': snapshot.market_data.get('open', 0) if snapshot.market_data else 0,
                    'high': snapshot.market_data.get('high', 0) if snapshot.market_data else 0,
                    'low': snapshot.market_data.get('low', 0) if snapshot.market_data else 0,
                    'close': snapshot.market_data.get('close', 0) if snapshot.market_data else 0,
                    'volume': snapshot.market_data.get('volume', 0) if snapshot.market_data else 0,
                }
                
                # Add strategy indicators
                if snapshot.strategy_indicators:
                    row.update(snapshot.strategy_indicators)
                
                data.append(row)
            
            df = pd.DataFrame(data)
            return df
            
        except Exception as e:
            logger.error(f"Error creating backtest DataFrame: {str(e)}")
            return None

    def get_backtest_results(self):
        """
        Get the backtest results array
        """
        return self.backtest
    
    def print_backtest_summary(self):
        """
        Print a formatted backtest summary to console
        """
        summary = self.get_backtest_summary()
        if "error" in summary:
            print(summary["error"])
            return
        
        print("\n" + "="*50)
        print("BACKTEST SUMMARY")
        print("="*50)
        print(f"Total Periods: {summary['total_periods']}")
        print(f"Buy Signals: {summary['buy_signals']} ({summary['buy_percentage']:.1f}%)")
        print(f"Sell Signals: {summary['sell_signals']} ({summary['sell_percentage']:.1f}%)")
        print(f"Hold Signals: {summary['hold_signals']} ({summary['hold_percentage']:.1f}%)")
        print(f"Date Range: {summary['start_date']} to {summary['end_date']}")
        print("="*50)
        
        # Show recent signals
        if self.backtest:
            print("\nLast 5 Signals:")
            for snapshot in self.backtest[-5:]:
                print(f"  {snapshot.current_time}: {snapshot.decision}")
        print()

    def clear_backtest(self):
        """
        Clear backtest results
        """
        self.backtest = []
        logger.info("Backtest results cleared")

    def get_historical_data(self, contract: Contract):
        logger.info(f"Getting historical data for {contract.symbol}...")
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
            raise Exception(f"Error getting historical data: {str(e)}")

    def get_latest_price(self, contract: Contract):
        logger.info(f"Getting latest price")
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