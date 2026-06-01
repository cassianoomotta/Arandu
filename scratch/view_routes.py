import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

print("Registered FastAPI Routes:")
for route in app.routes:
    methods = getattr(route, "methods", None)
    path = getattr(route, "path", None)
    summary = getattr(route, "summary", None)
    print(f"  {methods} {path} - {summary}")
