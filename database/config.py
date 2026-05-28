import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Settings:
    raw_db_url = os.getenv(
        "DATABASE_URL", 
        "sqlite:///arandu.db"
    )
    if raw_db_url.startswith("postgres://"):
        db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    else:
        db_url = raw_db_url

    # Auto-heal Supabase pooler connections missing project-ref in username
    if "pooler.supabase.com" in db_url and "://postgres:" in db_url:
        db_url = db_url.replace("://postgres:", "://postgres.albucbddugupigeaepbb:", 1)

    DATABASE_URL = db_url

    # Debug database URL (masked password)
    try:
        from sqlalchemy.engine.url import make_url
        parsed = make_url(db_url)
        print(f"PARSED_DB_URL: driver={parsed.drivername}, user={parsed.username}, host={parsed.host}, port={parsed.port}, database={parsed.database}")
        print(f"DEBUG: Password matches 'Arandu2026.'? {parsed.password == 'Arandu2026.'}")
        # Print first and last characters of the password to help identify it if mismatch
        if parsed.password:
            print(f"DEBUG: Password len={len(parsed.password)}, starts={parsed.password[0] if parsed.password else ''}, ends={parsed.password[-1] if parsed.password else ''}")
    except Exception as e:
        print(f"PARSED_DB_URL parsing error: {e}")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_DAILY_LIMIT: int = int(os.getenv("GEMINI_DAILY_LIMIT", "1500"))
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super_secret_key_change_me_in_production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

settings = Settings()
