from ib_insync import *
from src.utils.logger import logger
import threading
import asyncio
import nest_asyncio
import time
import os

CONNECTION_CHECK_INTERVAL = 30
MAX_RECONNECT_ATTEMPTS = 5

class ConnectionManager:
    """Handles IBKR connection, event loop, and monitoring in a standalone object so that
    other components (e.g., Trader) can focus on higher-level workflow logic.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        self.ib = IB()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        self.host = host or os.getenv('IBKR_HOST', None)
        self.port = int(port or os.getenv('IBKR_PORT', 0))

        self.reconnect_attempts = 0
        self.connection_monitor_thread: threading.Thread | None = None
        self.connection_monitor_running = False

        # Establish initial connection and kick-off background monitoring
        self.connect()
        self.start_connection_monitor()
        nest_asyncio.apply()

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _start_event_loop(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self._thread.start()

    def _execute(self, coro):
        """Synchronously execute a coroutine in the manager's event loop."""
        if self._loop is None:
            self._start_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def is_connected(self):
        try:
            return self.ib.isConnected()
        except Exception as e:
            logger.error(f"Error checking connection status: {str(e)}")
            return False

    def start_connection_monitor(self):
        if not self.connection_monitor_running:
            self.connection_monitor_running = True
            self.connection_monitor_thread = threading.Thread(target=self._connection_monitor_worker, daemon=True)
            self.connection_monitor_thread.start()
            logger.announcement("Connection monitor thread started", 'info')

    def stop_connection_monitor(self):
        self.connection_monitor_running = False
        if self.connection_monitor_thread and self.connection_monitor_thread.is_alive():
            self.connection_monitor_thread.join(timeout=5)
            logger.info("Connection monitor thread stopped")

    def _connection_monitor_worker(self):
        logger.info("Connection monitor worker started")
        while self.connection_monitor_running:
            logger.info("Checking IBKR connection...")
            try:
                if not self.is_connected():
                    logger.warning("Connection monitor detected lost connection. Attempting to reconnect...")
                    self.reconnect()
                else:
                    if self.reconnect_attempts > 0:
                        logger.info("Connection monitor confirmed connection is restored")
                        self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f"Error in connection monitor: {str(e)}")

            logger.success("Successfully connected to IBKR")
            time.sleep(CONNECTION_CHECK_INTERVAL)
        logger.info("Connection monitor worker stopped")

    def connect(self):
        logger.announcement("Connecting to IBKR...", 'info')
        try:
            async def _connect():
                max_attempts = 3
                attempt = 0
                while attempt < max_attempts:
                    try:
                        logger.info(f"Connecting to IBKR on {self.host}:{self.port} with clientId 1")
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
                self.reconnect_attempts = 0
            else:
                logger.error("Failed to connect to IBKR after multiple attempts")
            return connected
        except Exception as e:
            logger.error(f"Error connecting to IB: {str(e)}")
            return False

    def reconnect(self):
        self.reconnect_attempts += 1
        if self.reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
            logger.error(f"Maximum reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded. Manual intervention required.")
            return False

        logger.info(f"Reconnection attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}")
        try:
            # Attempt a clean disconnect first
            if self.ib.isConnected():
                try:
                    async def _disconnect():
                        self.ib.disconnect()
                    self._execute(_disconnect())
                except Exception as e:
                    logger.warning(f"Error during disconnect: {str(e)}")

            time.sleep(2)
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

    def disconnect(self):
        logger.info("Disconnecting from IBKR")
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
