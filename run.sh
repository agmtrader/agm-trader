#!/bin/bash

if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ $line =~ ^[^#] ]]; then
            eval "export $line"
        fi
    done < .env
fi

gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 0.0.0.0:${PORT} wsgi:application