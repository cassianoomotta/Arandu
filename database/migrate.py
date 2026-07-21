import logging
from sqlalchemy import text
from database.connection import engine
from database.models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_migrate")

def run_migrations():
    """Runs table creation and schema updates."""
    logger.info("Starting database schema migration...")
    Base.metadata.create_all(bind=engine)
    
    with engine.connect() as conn:
        # Dynamic migration: add translated_by_gemini column if missing
        try:
            conn.execute(text("ALTER TABLE news ADD COLUMN translated_by_gemini BOOLEAN DEFAULT FALSE"))
            conn.commit()
            logger.info("Added column 'translated_by_gemini' to news table.")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.info(f"Column 'translated_by_gemini' check: {e}")

        # Editorial Executivo columns
        editorial_cols = [
            ("editorial_status", "VARCHAR(50) DEFAULT 'pendente'"),
            ("editorial_title", "VARCHAR(255)"),
            ("editorial_summary", "TEXT"),
            ("editorial_category", "VARCHAR(100)"),
            ("editorial_tags", "TEXT"),
            ("meta_description", "TEXT"),
            ("editorial_scores", "JSON")
        ]
        for col_name, col_type in editorial_cols:
            try:
                conn.execute(text(f"ALTER TABLE news ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"Added column '{col_name}' to news table.")
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.info(f"Column '{col_name}' check: {e}")
                
    logger.info("Database migration completed successfully.")

if __name__ == "__main__":
    run_migrations()
