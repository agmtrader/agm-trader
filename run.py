from gevent import monkey
monkey.patch_all()

from flask import Flask
from flask_socketio import SocketIO
from src.app.spacetime import deploy_socket, deploy_api
from src.utils.logger import logger
import os
from dotenv import load_dotenv

load_dotenv()

def create_singularity():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'secret!'  # Add a secret key for security
    socketio = SocketIO(app, 
                       cors_allowed_origins="*", 
                       async_mode='gevent',
                       logger=False,
                       engineio_logger=False)
    
    deploy_socket(socketio)   
    deploy_api(app)

    return app, socketio

logger.announcement("Starting Singularity WebSocket server...", type='info')
singularity, singularity_socket = create_singularity()
logger.announcement("Singularity WebSocket server started successfully.", type='success')

# Get port from environment
port = int(os.getenv('SINGULARITY_SOCKET_PORT', 3333))
logger.announcement(f"Server listening on port {port}", type='info')

if __name__ == '__main__':
    singularity_socket.run(singularity, host='0.0.0.0', port=port, debug=False)

# This is needed for Gunicorn to access the app
application = singularity