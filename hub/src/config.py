import os
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.environ.get('EMQX_API_KEY')
DB_URI = os.environ.get('DB_URI')
HOST = os.environ.get('HOST')
EMQX_PORT = int(os.environ.get('EMQX_PORT'))
