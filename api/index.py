import sys
import os

# Force serverless environment flags at runtime entry
os.environ["VERCEL"] = "1"
os.environ["SERVERLESS"] = "1"
os.environ["DISABLE_SCHEDULER"] = "true"
os.environ["RUN_MIGRATIONS"] = "false"
os.environ["DISABLE_TIMEOUTS"] = "false"

# Add root directory to sys.path to allow importing main and database modules
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from main import app
