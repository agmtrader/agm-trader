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
from src.models.trader import db

from src.components.strategy import IchimokuBase
from src.lib.params import IchimokuBaseParams

SLEEP_TIME = 86400

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

        self.db = db

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
        logger.info("Connecting to IBKR")
        try:
            async def _connect():
                while True:
                    try:
                        await self.ib.connectAsync('127.0.0.1', 4002, clientId=1)
                        if self.ib.isConnected():
                            return True
                    except Exception as e:
                        logger.error(f"Error connecting to IB: {str(e)}")
                    logger.info("Waiting for connection...")
                    time.sleep(5)
            
            connected = self._execute(_connect())
            if connected:
                logger.success("Connected to IBKR")
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
                
                logger.success("Disconnected from IBKR")
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
        
        self.run_backtest(strategy_name)
        
        # TODO: Fix this so that historical data is saved in the contract object
        # TODO: Historical data must be updated once per timeframe used (must implement timeframe)
        for contract in strategy.params.contracts:
            strategy.params.historicalData[contract.symbol] = self.get_historical_data(contract)

        logger.announcement(f"Running strategy: {strategy.name}", 'info')
        self.running = True
        
        try:
            while True:

                if not self.running:
                    exit()

                self.account_summary = self.get_account_summary()

                strategy.params.openOrders = self.get_open_orders()
                strategy.params.executedOrders = self.get_completed_orders()
                strategy.params.positions = self.get_positions()

                # Run strategy
                self.decision = strategy.run()
                logger.announcement(f"Ran strategy at {datetime.now()}", 'info')
                logger.announcement(f"Decision: {self.decision}", 'success')

                # Store decision in database
                if self.decision:
                    #db.create('decision', {'decision': self.decision})
                    pass

                if self.decision != 'BUY' and self.decision != 'SELL':
                    time.sleep(SLEEP_TIME)
                    continue

                # TODO: Add exit logic
                if self.decision == 'EXIT':
                    continue

                # Create orders for the strategy
                order = strategy.create_order(self.decision)

                # Place orders in IBKRs
                self.place_order(order)

                # Update strategy params once more
                strategy.params.openOrders = self.get_open_orders()
                strategy.params.executedOrders = self.get_completed_orders()
                strategy.params.positions = self.get_positions()
                
                # Wait for 1 second before running the strategy again
                time.sleep(SLEEP_TIME)
                
        except Exception as e:
            logger.error(f"Error running strategy: {str(e)}")
            raise Exception(f"Error running strategy: {str(e)}")

    def run_backtest(self, strategy_name: str):
        """
        Run a backtest of the strategy using historical data.
        
        Args:
            strategy_name (str): Name of the strategy to backtest
            start_date (str, optional): Start date for backtest in 'YYYY-MM-DD' format
            end_date (str, optional): End date for backtest in 'YYYY-MM-DD' format
            
        Returns:
            pd.DataFrame: DataFrame containing backtest results
        """
        import pandas as pd
        from datetime import datetime, timedelta
        import numpy as np

        logger.announcement(f"Running backtest for {strategy_name}", 'info')
        
        if strategy_name == 'ICHIMOKU_BASE':
            strategy = IchimokuBase(IchimokuBaseParams())
        else:
            raise Exception(f"Strategy {strategy_name} not found")
        
        # Get historical data for all contracts
        historical_data = {}
        for contract in strategy.params.contracts:
            historical_data[contract.symbol] = self.get_historical_data(contract)
            
        # Convert historical data to DataFrame
        df = pd.DataFrame(historical_data[strategy.params.contracts[0].symbol])

        # Convert date strings to datetime
        df['date'] = pd.to_datetime(df['date'])
        
        # Initialize backtest results
        results = []
        position = 0
        entry_price = 0
        equity = 100  # Starting with 100 as base equity
        cumulative_returns = 0
        contracts = 12  # Default number of contracts
        
        # Run strategy on each historical data point
        for i in range(len(df)):
            current_data = df.iloc[:i+1]
            
            # Update strategy parameters with historical data
            strategy.params.historicalData = {contract.symbol: current_data.to_dict('records') 
                                           for contract in strategy.params.contracts}
            strategy.params.position = position
            strategy.params.openOrders = []
            strategy.params.executedOrders = []
            
            # Run strategy
            decision = strategy.run()
            
            # Calculate daily returns and equity
            daily_return = 0
            if position != 0:
                daily_return = (df.iloc[i]['close'] - df.iloc[i-1]['close']) / df.iloc[i-1]['close'] * 100
                cumulative_returns += daily_return
                equity *= (1 + daily_return/100)
            
            # Record results with enhanced data
            result = {
                'date': df.iloc[i]['date'],
                'open': df.iloc[i]['open'],
                'high': df.iloc[i]['high'],
                'low': df.iloc[i]['low'],
                'close': df.iloc[i]['close'],
                'volume': df.iloc[i]['volume'],
                'decision': decision,
                'position': position,
                'daily_return': daily_return,
                'cumulative_returns': cumulative_returns,
                'equity': equity,
                'entry_price': entry_price if position != 0 else None,
                'contracts': contracts,
                'tenkan': strategy.params.tenkan,
                'kijun': strategy.params.kijun,
                'psar_mes': strategy.params.psar_mes[-1] if strategy.params.psar_mes else None,
                'psar_mym': strategy.params.psar_mym[-1] if strategy.params.psar_mym else None
            }
            
            # Update position and entry price based on strategy decision
            if decision == 'BUY':
                position = 1
                entry_price = df.iloc[i]['close']
                contracts = strategy.params.number_of_contracts
            elif decision == 'SELLSHORT':
                position = -1
                entry_price = df.iloc[i]['close']
                contracts = strategy.params.number_of_contracts
            elif decision == 'STAY':
                # Keep current position and entry price
                pass
                
            results.append(result)
            
        # Convert results to DataFrame
        results_df = pd.DataFrame(results)
        
        # Save detailed results
        results_df.to_csv('backtest_results.csv', index=False)
        
        logger.success(f"Backtest completed successfully")
        return results_df

    def get_historical_data(self, contract: Contract):
        logger.info(f"Getting historical data")
        try:
            async def _get_historical_data():
                historical_data_response = self.ib.reqHistoricalData(contract, endDateTime='', durationStr='1 Y', barSizeSetting='1 day', whatToShow='TRADES', useRTH=1)
                historical_data = []
                for bar in historical_data_response:
                    historical_data.append(bar.dict())
                
                return historical_data
            
            historical_data = self._execute(_get_historical_data())
            logger.success(f"Successfully got historical data")
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
            logger.success(f"Successfully got latest price")
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
            logger.success(f"Successfully got account summary")
            return account_summary
        except Exception as e:
            logger.error(f"Error getting account summary: {str(e)}")
            raise Exception(f"Error getting account summary: {str(e)}")

    def get_positions(self):
        logger.info("Getting positions")
        try:
            async def _get_positions():
                positions = self.ib.positions()
                logger.info(f"You have {len(positions)} positions overall")
                return positions
            
            positions = self._execute(_get_positions())
            logger.success(f"Successfully got positions: {positions}")
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
                        'contract': order.contract.dict(),
                        'orderStatus': order.orderStatus.dict(),
                        'isActive': order.isActive(),
                        'isDone': order.isDone(),
                        'filled': order.filled(),
                        'remaining': order.remaining(),
                    })
                logger.info(f"Successfully got {len(orders)} completed orders")
                return orders
            
            completed_orders = self._execute(_get_completed_orders())
            logger.success(f"Successfully got {len(completed_orders)} completed orders")
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
                for order in orders_response:
                    order_dict = order.dict()
                    order_dict['softDollarTier'] = order.softDollarTier.dict()
                    orders.append(order_dict)
                logger.info(f"Successfully got {len(orders)} open orders")
                return orders
            
            open_orders = self._execute(_get_open_orders())
            logger.success(f"Successfully got {len(open_orders)} open orders")
            return open_orders
        except Exception as e:
            logger.error(f"Error getting open orders: {str(e)}")
            raise Exception(f"Error getting open orders: {str(e)}")

    def place_order(self, order: Order):
        logger.info(f"Placing order: {order}")
        try:
            async def _place_order():

                # TODO Fix this
                contract = self.strategy.params.contracts[0]
                self.ib.qualifyContracts(contract)

                for o in order:
                    print(o)
                    self.ib.placeOrder(contract, o)

                return True
            
            self._execute(_place_order())
            logger.success(f"Successfully placed order")
            return True
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            raise Exception(f"Error placing order: {str(e)}")

class TraderSnapshot:

    def __init__(self, trader: Trader):
        logger.announcement("Creating Trader Snapshot", 'info')
        self.strategy = trader.strategy
        self.decision = trader.decision
        self.account_summary = trader.account_summary
        self.decision_history = json.loads(trader.db.read('decision').data.decode('utf-8'))

    def to_dict(self):
        return {
            'strategy': self.strategy.to_dict(),
            'decision': self.decision,
            'account_summary': self.account_summary,
            'decision_history': self.decision_history
        }