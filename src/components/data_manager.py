from ib_insync import *
from src.utils.logger import logger
from src.components.connection_manager import ConnectionManager
import math
import time

class DataManager:
    """
    Encapsulates read-only data access to IBKR. All API calls are executed through
    the event loop managed by the provided ConnectionManager instance.
    """

    def __init__(self, conn: ConnectionManager):
        self.conn = conn
        self.ib = conn.ib

    def get_historical_data(self, contract: Contract, duration: str = '5 Y', bar_size: str = '1 day'):
        logger.info(f"Getting historical data for {contract.symbol}…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting historical data. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get historical data - no connection to IBKR")

        async def _get():
            resp = self.ib.reqHistoricalData(contract, endDateTime='', durationStr=duration,
                                             barSizeSetting=bar_size, whatToShow='TRADES', useRTH=1)
            return [bar.dict() for bar in resp]

        try:
            data = self.conn._execute(_get())
            logger.success("Successfully got historical data.")
            return data
        except Exception as e:
            logger.error(f"Error getting historical data: {str(e)}")
            # One retry after reconnect
            if self.conn.reconnect():
                try:
                    data = self.conn._execute(_get())
                    logger.success("Successfully got historical data after reconnection.")
                    return data
                except Exception as retry_e:
                    logger.error(f"Error after reconnection: {str(retry_e)}")
            raise

    def get_latest_price(self, contract: Contract):
        logger.info("Getting latest price…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting latest price. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get latest price - no connection to IBKR")

        async def _get():
            self.ib.reqMarketDataType(3)
            md = self.ib.reqMktData(contract, '233', False, False, [])
            while math.isnan(md.last):
                self.ib.sleep(0.05)
                logger.info("Waiting for market data…")
            return md.last

        try:
            price = self.conn._execute(_get())
            logger.success("Successfully got latest price.")
            return price
        except Exception as e:
            logger.error(f"Error getting latest price: {str(e)}")
            raise

    def get_account_summary(self):
        logger.info("Getting account summary…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting account summary. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get account summary - no connection to IBKR")

        async def _get():
            resp = self.ib.accountSummary()
            return [{
                'account': s.account,
                'tag': s.tag,
                'value': s.value,
                'currency': s.currency,
                'modelCode': s.modelCode,
            } for s in resp]

        try:
            summary = self.conn._execute(_get())
            logger.success("Successfully got account summary.")
            return summary
        except Exception as e:
            logger.error(f"Error getting account summary: {str(e)}")
            raise

    def get_positions(self):
        logger.info("Getting positions…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting positions. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get positions - no connection to IBKR")

        async def _get():
            resp = self.ib.positions()
            positions = []
            for p in resp:
                positions.append({
                    'account': p.account,
                    'contract': {
                        'symbol': p.contract.symbol,
                        'secType': p.contract.secType,
                        'exchange': p.contract.exchange,
                        'currency': getattr(p.contract, 'currency', 'USD'),
                    },
                    'position': p.position,
                    'avgCost': p.avgCost,
                })
            return positions

        try:
            positions = self.conn._execute(_get())
            logger.success(f"Successfully got {len(positions)} positions.")
            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            raise

    def get_completed_orders(self):
        logger.info("Getting completed orders…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting completed orders. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get completed orders - no connection to IBKR")

        async def _get():
            resp = self.ib.reqCompletedOrders(False)
            orders = []
            for o in resp:
                orders.append({
                    'contract': {
                        'symbol': o.contract.symbol,
                        'secType': o.contract.secType,
                        'exchange': o.contract.exchange,
                        'currency': getattr(o.contract, 'currency', 'USD'),
                    },
                    'orderStatus': {
                        'orderId': o.orderStatus.orderId,
                        'status': o.orderStatus.status,
                        'filled': o.orderStatus.filled,
                        'remaining': o.orderStatus.remaining,
                        'avgFillPrice': o.orderStatus.avgFillPrice,
                    },
                    'isActive': o.isActive(),
                    'isDone': o.isDone(),
                    'filled': o.filled(),
                    'remaining': o.remaining(),
                })
            return orders

        try:
            orders = self.conn._execute(_get())
            logger.success(f"Successfully got {len(orders)} completed orders.")
            return orders
        except Exception as e:
            logger.error(f"Error getting completed orders: {str(e)}")
            raise

    def get_open_orders(self):
        logger.info("Getting open orders…")
        if not self.conn.is_connected():
            logger.warning("No connection when getting open orders. Attempting reconnection…")
            if not self.conn.reconnect():
                raise Exception("Cannot get open orders - no connection to IBKR")

        async def _get():
            resp = self.ib.openOrders()
            orders = []
            for t in resp:
                orders.append({
                    'orderId': t.orderId,
                    'clientId': t.clientId,
                    'permId': t.permId,
                    'action': t.action,
                    'totalQuantity': t.totalQuantity,
                    'orderType': t.orderType,
                    'lmtPrice': t.lmtPrice,
                    # … many more fields omitted for brevity …
                })
            return orders

        try:
            orders = self.conn._execute(_get())
            logger.success(f"Successfully got {len(orders)} open orders.")
            return orders
        except Exception as e:
            logger.error(f"Error getting open orders: {str(e)}")
            raise
