import sys
import os
import traceback

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Force serverless environment flags at runtime entry
os.environ["VERCEL"] = "1"
os.environ["SERVERLESS"] = "1"
os.environ["DISABLE_SCHEDULER"] = "true"
os.environ["RUN_MIGRATIONS"] = "false"
os.environ["DISABLE_TIMEOUTS"] = "false"

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

app = FastAPI(title="Arandu Diagnostic & Production API")

@app.get("/api/health")
def health_check():
    import_main_error = None
    main_imported = False
    try:
        import main
        main_imported = True
    except Exception as e:
        import_main_error = traceback.format_exc()

    return {
        "status": "healthy",
        "python_version": sys.version,
        "main_imported": main_imported,
        "import_error": import_main_error,
        "env_keys": [k for k in os.environ.keys() if not any(s in k.lower() for s in ['key', 'secret', 'token', 'pass', 'database'])]
    }

# Forward /api/noticias dynamically to main if possible
@app.get("/api/noticias")
def proxy_noticias(page: int = 1, size: int = 20, source_id: int = None, send_status: str = None, editorial_status: str = None, order_by: str = "published"):
    try:
        import main
        from fastapi.responses import Response
        res = Response()
        return main.get_news(response=res, page=page, size=size, source_id=source_id, send_status=send_status, editorial_status=editorial_status, order_by=order_by)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to fetch news from main",
                "message": str(e),
                "traceback": traceback.format_exc().splitlines()
            }
        )

# Catch-all route for any other API route
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all(path: str = ""):
    try:
        import main
        # If main is loaded, forward using ASGI app
        return await main.app(scope=None, receive=None, send=None)
    except Exception as e:
        return JSONResponse(
            status_code=404,
            content={"message": f"Route /api/{path} not found or main unavailable", "error": str(e)}
        )
