import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

def is_serverless() -> bool:
    serverless_keys = {
        "VERCEL", "VERCEL_ENV", "VERCEL_REGION", 
        "NOW_REGION", "AWS_LAMBDA_FUNCTION_NAME", 
        "LAMBDA_TASK_ROOT", "AWS_EXECUTION_ENV", "SERVERLESS"
    }
    return any(k in os.environ for k in serverless_keys)

class Settings:
    default_sqlite = "sqlite:////tmp/arandu.db" if is_serverless() else "sqlite:///arandu.db"
    raw_db_url = os.getenv("DATABASE_URL", default_sqlite).strip()
    if raw_db_url.startswith("postgres://"):
        DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
    else:
        DATABASE_URL = raw_db_url

    # Cleaned up debug statements

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    _gemini_limit = os.getenv("GEMINI_DAILY_LIMIT", "1500")
    GEMINI_DAILY_LIMIT: int = int(_gemini_limit) if _gemini_limit and _gemini_limit.isdigit() else 1500
    JWT_SECRET: str = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Disable time-capping if not running on Vercel/serverless (local execution)
    DISABLE_TIMEOUTS: bool = os.getenv(
        "DISABLE_TIMEOUTS", 
        "false" if is_serverless() else "true"
    ).lower() == "true"

settings = Settings()

