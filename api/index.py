import sys
import os

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import the main Flask application
from fingroww_market_server import app

# WSGI application callable for Vercel Serverless
app = app

