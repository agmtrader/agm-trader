#!/bin/bash

# Start Gunicorn with environment variables and increased timeout
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ $line =~ ^[^#] ]]; then
            eval "export $line"
        fi
    done < .env
fi

# Start Gunicorn with environment variables
gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 0.0.0.0:${PORT} wsgi:application