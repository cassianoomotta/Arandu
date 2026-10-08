import sys
import os
import traceback

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

try:
    from main import app
except Exception as startup_err:
    tb_str = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, HTMLResponse
    
    app = FastAPI(title="Arandu Emergency Fallback")
    
    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    def catch_all_fallback(path: str = ""):
        # If user is asking for an HTML page or static file, try to serve it directly
        candidate_paths = [
            os.path.join(root_dir, path) if path else os.path.join(root_dir, "index.html"),
            os.path.join(root_dir, f"{path}.html") if path and not path.endswith(".html") else None,
            os.path.join(os.getcwd(), path) if path else None,
        ]
        for c_path in candidate_paths:
            if c_path and os.path.exists(c_path) and os.path.isfile(c_path):
                try:
                    with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
                        return HTMLResponse(content=f.read())
                except Exception:
                    pass
                    
        return JSONResponse(
            status_code=500,
            content={
                "error": "Backend Startup Exception",
                "message": str(startup_err),
                "traceback": tb_str.splitlines()
            }
        )
