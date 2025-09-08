from flask import request
from flask_socketio import emit
from src.utils.logger import logger
from src.components.trader import Trader

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

    @socketio.on('account_summary')
    def account_summary():
        try:
            logger.announcement("Account summary requested.", 'info')
            account_summary = trader.account_summary
            emit('account_summary', account_summary, broadcast=True)
        except Exception as e:
            logger.error(f"Error getting account summary: {str(e)}")
            emit('account_summary', str(e), broadcast=True)

    @socketio.on('history')
    def history():
        try:
            logger.announcement("History requested.", 'info')
            history = trader.history
            emit('history_data', history, broadcast=True)
        except Exception as e:
            logger.error(f"Error getting history: {str(e)}")
            emit('history_data', str(e), broadcast=True)
            
    @socketio.on('trades')
    def trades():
        try:
            logger.announcement("Trades requested.", 'info')
            trades = [trade.to_dict() for trade in trader.trades]
            emit('trades_data', trades, broadcast=True)
        except Exception as e:
            logger.error(f"Error getting trades: {str(e)}")
            emit('trades_data', str(e), broadcast=True)