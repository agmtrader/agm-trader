from flask import request
from flask_socketio import emit
from src.utils.logger import logger
from src.components.trader import Trader, TraderSnapshot

trader = Trader()

def deploy_main_routes(socketio):
    @socketio.on('connect')
    def handle_connect():
        logger.announcement("Client connecting...", 'info')
        try:
            if trader:
                emit('connected', 'Connected', broadcast=True)
                logger.announcement("Client connected.", 'success')
        except Exception as e:
            logger.error(f"Error connecting client: {str(e)}")

    @socketio.on('disconnect')
    def handle_disconnect():
        client_id = request.sid
        logger.announcement(f"Client {client_id} disconnecting...", 'info')
        emit('disconnected', {'client_id': client_id}, broadcast=True)
        logger.announcement(f"Client {client_id} disconnected.", 'success')

    @socketio.on('ping')
    def ping():
        try:
            logger.announcement("Ping received.", 'info')
            emit('pong', TraderSnapshot(trader).to_dict(), broadcast=True)
        except Exception as e:
            logger.error(f"Error pinging Trader: {str(e)}")
            emit('pong', str(e), broadcast=True)

    @socketio.on('backtest')
    def backtest():
        try:
            logger.announcement("Backtest data requested.", 'info')
            backtest_data = [snapshot.to_dict() for snapshot in trader.backtest] if trader.backtest else []
            emit('backtest_data', backtest_data, broadcast=True)
        except Exception as e:
            logger.error(f"Error getting backtest data: {str(e)}")
            emit('backtest_data', str(e), broadcast=True)