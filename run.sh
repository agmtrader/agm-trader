#!/bin/bash

# Load environment variables first
export $(cat .env | xargs)

# Start Gunicorn with environment variables
gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 0.0.0.0:$SOCKET_PORT wsgi:application