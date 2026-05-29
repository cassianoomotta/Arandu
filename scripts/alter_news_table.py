import sys
import os

# Add parent folder (project root) to sys.path to allow standalone execution
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import logging
from sqlalchemy import text
from database.connection import engine, get_db_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def alter_table():
    """
    Safely adds curation columns to the news table if they don't exist.
    """
    columns_to_add = [
        ("relevance_score", "INTEGER"),
        ("ai_justification", "TEXT"),
        ("category", "VARCHAR(100)"),
        ("priority", "VARCHAR(50)"),
        ("is_curated", "BOOLEAN DEFAULT FALSE NOT NULL"),
        ("curated_at", "TIMESTAMP")
    ]
    
    db_type = "postgresql" if "postgresql" in str(engine.url) else "sqlite"
    logger.info(f"Detected database type: {db_type}")
    
    with get_db_session() as session:
        # Check existing columns
        if db_type == "sqlite":
            result = session.execute(text("PRAGMA table_info(news)"))
            existing_columns = {row[1] for row in result.fetchall()}
        else:
            # PostgreSQL
            result = session.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'news'"
            ))
            existing_columns = {row[0] for row in result.fetchall()}
            
        logger.info(f"Existing columns in 'news' table: {existing_columns}")
        
        # Add missing columns
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                logger.info(f"Adding column '{col_name}' ({col_type}) to 'news' table...")
                try:
                    session.execute(text(f"ALTER TABLE news ADD COLUMN {col_name} {col_type}"))
                    session.commit()
                    logger.info(f"Column '{col_name}' added successfully.")
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error adding column '{col_name}': {e}")
            else:
                logger.info(f"Column '{col_name}' already exists.")
                
        # Create indexes if they don't exist
        try:
            logger.info("Creating index ix_news_is_curated...")
            session.execute(text("CREATE INDEX IF NOT EXISTS ix_news_is_curated ON news(is_curated)"))
            logger.info("Creating index ix_news_relevance_score...")
            session.execute(text("CREATE INDEX IF NOT EXISTS ix_news_relevance_score ON news(relevance_score)"))
            session.commit()
            logger.info("Indexes verified/created successfully.")
        except Exception as e:
            session.rollback()
            logger.warning(f"Could not create indexes via raw SQL (this is normal if they already exist): {e}")

if __name__ == "__main__":
    alter_table()
    logger.info("Migration check completed!")
