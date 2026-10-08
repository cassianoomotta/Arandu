import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the SQLAlchemy Engine
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        except Exception as e:
            logger.warning(f"Failed to set SQLite PRAGMA: {e}")
else:
    # pool_pre_ping=True helps detect and recover from dropped connections automatically
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600
    )

# Create a sessionmaker factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

_tables_initialized = False

def ensure_sqlite_tables():
    global _tables_initialized
    if not _tables_initialized and settings.DATABASE_URL.startswith("sqlite"):
        try:
            from database.models import Base
            Base.metadata.create_all(bind=engine)
            _tables_initialized = True
        except Exception as e:
            logger.warning(f"Failed to ensure sqlite tables: {e}")

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager that provides a transactional scope around a series of operations.
    It automatically commits the transaction on success, rolls back on exceptions,
    and ensures the session is closed.
    """
    ensure_sqlite_tables()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database transaction error: {str(e)}")
        raise e
    finally:
        session.close()
