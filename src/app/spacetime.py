from flask import request
from flask_socketio import emit
from src.utils.logger import logger
from src.components.singularity import Singularity, SingularitySnapshot
from src.utils.response import Response

from flask import Blueprint

logger.announcement("Starting Singularity", 'info')
singularity = Singularity()
logger.announcement("Singularity initialized and connected to IBKR", 'success')

def deploy_api(app):
    ibkr_routes = Blueprint('ibkr', __name__)
    @ibkr_routes.route('/get_latest_price', methods=['POST'])
    def get_latest_price():
        data = request.json
        ticker = data['ticker']
        return {'price': singularity.get_latest_price(ticker)}
    
    app.register_blueprint(ibkr_routes, url_prefix='/ibkr')

def deploy_socket(socketio):
    @socketio.on('connect')
    def handle_connect():
        logger.announcement("Client connecting", 'info')
        try:
            if singularity:
                emit('connected', Response.success(SingularitySnapshot(singularity).to_dict()), broadcast=True)
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
            emit('pong', Response.success(SingularitySnapshot(singularity).to_dict()), broadcast=True)
        except Exception as e:
            logger.error(f"Error pinging Singularity: {str(e)}")
            emit('pong', Response.error(str(e)), broadcast=True)