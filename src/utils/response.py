from flask import Response
import json
import functools

def format_response(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        data = func(*args, **kwargs)
        if isinstance(data, Response):
            return data
        return Response(json.dumps(data), status=200, mimetype='application/json')
    return wrapper 