from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
from dotenv import load_dotenv
import os
from run import application

load_dotenv()

if __name__ == '__main__':
    server = pywsgi.WSGIServer(('0.0.0.0', os.getenv('PORT')), application, handler_class=WebSocketHandler)
    server.serve_forever() 