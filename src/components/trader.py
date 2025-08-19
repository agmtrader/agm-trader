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
CONNECTION_CHECK_INTERVAL = 30
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
        self.close_all_positions()

        logger.announcement(f"Running strategy: {strategy.name}", 'info')
        
        self.running = True
        
        try:
            while True:

                if not self.running:
                    self.stop_connection_monitor()
                    exit()

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
                        self.place_order(order)
                        # logger.warning("Order placement is currently disabled for safety")
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
                        'orderId': trade.orderId,
                        'clientId': trade.clientId,
                        'permId': trade.permId,
                        'action': trade.action,
                        'totalQuantity': trade.totalQuantity,
                        'orderType': trade.orderType,
                        'lmtPrice': trade.lmtPrice,
                        'auxPrice': trade.auxPrice,
                        'tif': trade.tif,
                        'activeStartTime': trade.activeStartTime,
                        'activeStopTime': trade.activeStopTime,
                        'ocaGroup': trade.ocaGroup,
                        'ocaType': trade.ocaType,
                        'orderRef': trade.orderRef,
                        'transmit': trade.transmit,
                        'parentId': trade.parentId,
                        'blockOrder': trade.blockOrder,
                        'sweepToFill': trade.sweepToFill,
                        'displaySize': trade.displaySize,
                        'triggerMethod': trade.triggerMethod,
                        'outsideRth': trade.outsideRth,
                        'hidden': trade.hidden,
                        'goodAfterTime': trade.goodAfterTime,
                        'goodTillDate': trade.goodTillDate,
                        'rule80A': trade.rule80A,
                        'allOrNone': trade.allOrNone,
                        'minQty': trade.minQty,
                        'percentOffset': trade.percentOffset,
                        'overridePercentageConstraints': trade.overridePercentageConstraints,
                        'trailStopPrice': trade.trailStopPrice,
                        'trailingPercent': trade.trailingPercent,
                        'faGroup': trade.faGroup,
                        'faProfile': trade.faProfile,
                        'faMethod': trade.faMethod,
                        'faPercentage': trade.faPercentage,
                        'designatedLocation': trade.designatedLocation,
                        'openClose': trade.openClose,
                        'origin': trade.origin,
                        'shortSaleSlot': trade.shortSaleSlot,
                        'exemptCode': trade.exemptCode,
                        'discretionaryAmt': trade.discretionaryAmt,
                        'eTradeOnly': trade.eTradeOnly,
                        'firmQuoteOnly': trade.firmQuoteOnly,
                        'nbboPriceCap': trade.nbboPriceCap,
                        'optOutSmartRouting': trade.optOutSmartRouting,
                        'auctionStrategy': trade.auctionStrategy,
                        'startingPrice': trade.startingPrice,
                        'stockRefPrice': trade.stockRefPrice,
                        'delta': trade.delta,
                        'stockRangeLower': trade.stockRangeLower,
                        'stockRangeUpper': trade.stockRangeUpper,
                        'randomizePrice': trade.randomizePrice,
                        'randomizeSize': trade.randomizeSize,
                        'volatility': trade.volatility,
                        'volatilityType': trade.volatilityType,
                        'deltaNeutralOrderType': trade.deltaNeutralOrderType,
                        'deltaNeutralAuxPrice': trade.deltaNeutralAuxPrice,
                        'deltaNeutralConId': trade.deltaNeutralConId,
                        'deltaNeutralSettlingFirm': trade.deltaNeutralSettlingFirm,
                        'deltaNeutralClearingAccount': trade.deltaNeutralClearingAccount,
                        'deltaNeutralClearingIntent': trade.deltaNeutralClearingIntent,
                        'deltaNeutralOpenClose': trade.deltaNeutralOpenClose,
                        'deltaNeutralShortSale': trade.deltaNeutralShortSale,
                        'deltaNeutralShortSaleSlot': trade.deltaNeutralShortSaleSlot,
                        'deltaNeutralDesignatedLocation': trade.deltaNeutralDesignatedLocation,
                        'continuousUpdate': trade.continuousUpdate,
                        'referencePriceType': trade.referencePriceType,
                        'basisPoints': trade.basisPoints,
                        'basisPointsType': trade.basisPointsType,
                        'scaleInitLevelSize': trade.scaleInitLevelSize,
                        'scaleSubsLevelSize': trade.scaleSubsLevelSize,
                        'scalePriceIncrement': trade.scalePriceIncrement,
                        'scalePriceAdjustValue': trade.scalePriceAdjustValue,
                        'scalePriceAdjustInterval': trade.scalePriceAdjustInterval,
                        'scaleProfitOffset': trade.scaleProfitOffset,
                        'scaleAutoReset': trade.scaleAutoReset,
                        'scaleInitPosition': trade.scaleInitPosition,
                        'scaleInitFillQty': trade.scaleInitFillQty,
                        'scaleRandomPercent': trade.scaleRandomPercent,
                        'scaleTable': trade.scaleTable,
                        'hedgeType': trade.hedgeType,
                        'hedgeParam': trade.hedgeParam,
                        'account': trade.account,
                        'settlingFirm': trade.settlingFirm,
                        'clearingAccount': trade.clearingAccount,
                        'clearingIntent': trade.clearingIntent,
                        'algoStrategy': trade.algoStrategy,
                        'algoParams': trade.algoParams,
                        'smartComboRoutingParams': trade.smartComboRoutingParams,
                        'algoId': trade.algoId,
                        'whatIf': trade.whatIf,
                        'notHeld': trade.notHeld,
                        'solicited': trade.solicited,
                        'modelCode': trade.modelCode,
                        'orderComboLegs': trade.orderComboLegs,
                        'orderMiscOptions': trade.orderMiscOptions,
                        'referenceContractId': trade.referenceContractId,
                        'peggedChangeAmount': trade.peggedChangeAmount,
                        'isPeggedChangeAmountDecrease': trade.isPeggedChangeAmountDecrease,
                        'referenceChangeAmount': trade.referenceChangeAmount,
                        'referenceExchangeId': trade.referenceExchangeId,
                        'adjustedOrderType': trade.adjustedOrderType,
                        'triggerPrice': trade.triggerPrice,
                        'adjustedStopPrice': trade.adjustedStopPrice,
                        'adjustedStopLimitPrice': trade.adjustedStopLimitPrice,
                        'adjustedTrailingAmount': trade.adjustedTrailingAmount,
                        'adjustableTrailingUnit': trade.adjustableTrailingUnit,
                        'lmtPriceOffset': trade.lmtPriceOffset,
                        'conditions': trade.conditions,
                        'conditionsCancelOrder': trade.conditionsCancelOrder,
                        'conditionsIgnoreRth': trade.conditionsIgnoreRth,
                        'extOperator': trade.extOperator,
                        'cashQty': trade.cashQty,
                        'mifid2DecisionMaker': trade.mifid2DecisionMaker,
                        'mifid2DecisionAlgo': trade.mifid2DecisionAlgo,
                        'mifid2ExecutionTrader': trade.mifid2ExecutionTrader,
                        'mifid2ExecutionAlgo': trade.mifid2ExecutionAlgo,
                        'dontUseAutoPriceForHedge': trade.dontUseAutoPriceForHedge,
                        'isOmsContainer': trade.isOmsContainer,
                        'discretionaryUpToLimitPrice': trade.discretionaryUpToLimitPrice,
                        'autoCancelDate': trade.autoCancelDate,
                        'filledQuantity': trade.filledQuantity,
                        'refFuturesConId': trade.refFuturesConId,
                        'autoCancelParent': trade.autoCancelParent,
                        'shareholder': trade.shareholder,
                        'imbalanceOnly': trade.imbalanceOnly,
                        'routeMarketableToBbo': trade.routeMarketableToBbo,
                        'parentPermId': trade.parentPermId,
                        'usePriceMgmtAlgo': trade.usePriceMgmtAlgo,
                        'duration': trade.duration,
                        'postToAts': trade.postToAts,
                        'advancedErrorOverride': trade.advancedErrorOverride,
                        'manualOrderTime': trade.manualOrderTime,
                        'minTradeQty': trade.minTradeQty,
                        'minCompeteSize': trade.minCompeteSize,
                        'competeAgainstBestOffset': trade.competeAgainstBestOffset,
                        'midOffsetAtWhole': trade.midOffsetAtWhole,
                        'midOffsetAtHalf': trade.midOffsetAtHalf,
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