
import requests
import os
from src.utils.logger import logger

url = f"http://127.0.0.1:{os.getenv('LF_API_PORT')}"

def access_api(endpoint, method='GET', data=None):
    try:
        # Add timeout to prevent hanging
        auth = requests.post(url + '/login', json={'token': 'laserfocused'})
        
        response = requests.request(method, url + endpoint, json=data, headers={
            'Authorization': f'Bearer {auth.json()["access_token"]}'
        })
        
        try:
            return response.json()
        except:
            return response.content
            
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {str(e)}")
        raise