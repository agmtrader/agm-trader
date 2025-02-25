from flask import Flask
from flask_socketio import SocketIO
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
import os
from dotenv import load_dotenv
from src.utils.logger import logger

load_dotenv()

def create_app():

    app = Flask(__name__)
    socket = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

    from src.app.main import deploy_main_routes
    deploy_main_routes(socket)

    @app.route('/')
    def index():
        return {'title': 'WebSocket server'}
    
    return app, socket

logger.announcement("Starting WebSocket server...", type='info')
app, socket = create_app()

wsgi_server = pywsgi.WSGIServer(('0.0.0.0', os.getenv('PORT')), app, handler_class=WebSocketHandler)
application = app

if __name__ == '__main__':
    wsgi_server.serve_forever()

logger.announcement("WebSocket server started successfully.", type='success')