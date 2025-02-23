from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
from run import application
import os
from dotenv import load_dotenv

load_dotenv()

if __name__ == '__main__':
    port = int(os.getenv('OASIS_SOCKET_PORT', 3333))
    server = pywsgi.WSGIServer(('0.0.0.0', port), application, handler_class=WebSocketHandler)
    server.serve_forever() 