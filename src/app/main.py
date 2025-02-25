from flask import request
from flask_socketio import emit
from src.utils.logger import logger
from src.components.trader import Trader, TraderSnapshot
from src.utils.response import Response

logger.announcement("Starting Trader", 'info')
trader = Trader()
logger.announcement("Trader initialized and connected to IBKR", 'success')

def deploy_main_routes(socketio):
    @socketio.on('connect')
    def handle_connect():
        logger.announcement("Client connecting", 'info')
        try:
            if trader:
                emit('connected', Response.success(TraderSnapshot(trader).to_dict()), broadcast=True)
                logger.announcement("Client connected", 'success')
                return
            emit('connected', Response.success(None), broadcast=True)
            logger.announcement("Client connected", 'success')
            return
        except Exception as e:
            logger.error(f"{str(e)}")
            return

    @socketio.on('disconnect')
    def handle_disconnect():
        client_id = request.sid
        logger.announcement(f"Client {client_id} disconnecting...", 'info')
        emit('disconnected', Response.success(client_id), broadcast=True)
        logger.announcement(f"Client {client_id} disconnected", 'success')

    @socketio.on('ping')
    def ping():
        try:
            emit('pong', Response.success(TraderSnapshot(trader).to_dict()), broadcast=True)
        except Exception as e:
            logger.error(f"Error pinging Trader: {str(e)}")
            emit('pong', Response.error(str(e)), broadcast=True)