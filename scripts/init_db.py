import sys
import os

# Add parent folder (project root) to sys.path to allow standalone execution
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import logging
from datetime import datetime
from database.connection import engine, get_db_session
from database.models import Base, Source, SourceType, User, UserRole, News, SendStatus

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def create_tables():
    """
    Creates all defined database tables.
    """
    logger.info("Connecting to the database and creating tables...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tables created successfully!")
    except Exception as e:
        logger.error(f"Error creating tables: {str(e)}")
        sys.exit(1)

def seed_database():
    """
    Seeds initial data (Sources, Users, and standard entries) using the context manager session.
    """
    logger.info("Seeding database with default records...")
    
    # 1. Seed Sources
    sources_to_add = [
        # --- Nacionais ---
        Source(
            name="Canaltech",
            rss_url="https://canaltech.com.br/rss/",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="Olhar Digital",
            rss_url="https://olhardigital.com.br/feed/",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="Tecmundo",
            rss_url="https://www.tecmundo.com.br/rss",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="Tecnoblog",
            rss_url="https://tecnoblog.net/feed/",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="InfoMoney",
            rss_url="https://www.infomoney.com.br/feed/",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="G1 Tecnologia",
            rss_url="https://g1.globo.com/rss/g1/tecnologia/",
            type=SourceType.NACIONAL,
            active=True
        ),
        Source(
            name="G1 Empreendedorismo",
            rss_url="https://g1.globo.com/rss/g1/economia/empreendedorismo/",
            type=SourceType.NACIONAL,
            active=True
        ),
        # --- Internacionais & Referências Globais ---
        Source(
            name="TechCrunch",
            rss_url="https://techcrunch.com/feed/",
            type=SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="Wired",
            rss_url="https://www.wired.com/feed/rss",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="VentureBeat",
            rss_url="https://venturebeat.com/feed/",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="MIT Technology Review",
            rss_url="https://www.technologyreview.com/feed/",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        # --- Blogs Corporativos & Pesquisa ---
        Source(
            name="Google Research Blog",
            rss_url="https://feeds.feedburner.com/blogspot/gJZg",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="AWS News Blog",
            rss_url="https://aws.amazon.com/blogs/aws/feed/",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        # --- Blogs de Opinião e Filosofia de Negócios ---
        Source(
            name="Paul Graham Essays",
            rss_url="http://www.paulgraham.com/rss.html",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        # --- Blogs de Universidades de Negócios, Tecnologia e Empreendedorismo ---
        Source(
            name="Harvard Business Review",
            rss_url="https://feeds.feedburner.com/harvardbusiness",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="MIT Sloan Management Review",
            rss_url="https://sloanreview.mit.edu/feed/",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        ),
        Source(
            name="LSE Business Review",
            rss_url="https://blogs.lse.ac.uk/businessreview/feed/",
            type=SourceType.INTERNICIONAL if hasattr(SourceType, 'INTERNICIONAL') else SourceType.INTERNACIONAL,
            active=True
        )
    ]
    
    # 2. Seed Users (passwords hashed using SHA-256 for cross-platform ease)
    users_to_add = [
        User(
            name="Admin Arandu",
            email="admin@arandu.com.br",
            password_hash="1f8ae10bd671238aac7a53620e271672881bc9b316c6b9380c9a1512027aa263", # SHA-256 of Aranduadmin
            role=UserRole.ADMIN
        ),
        User(
            name="Leitor Teste",
            email="leitor@arandu.com.br",
            password_hash="5bb586e91c868fc9a5f274046be699d1ed7059b29e5195025a1882a17831152f", # SHA-256 of leitor123
            role=UserRole.LEITOR
        )
    ]
    
    # Use the connection Context Manager safely
    try:
        with get_db_session() as session:
            # 1. Incremental Seed for Sources
            added_sources = 0
            updated_sources = 0
            for src in sources_to_add:
                existing = session.query(Source).filter(Source.name == src.name).first()
                if existing:
                    if existing.rss_url != src.rss_url or existing.type != src.type:
                        existing.rss_url = src.rss_url
                        existing.type = src.type
                        existing.active = True
                        updated_sources += 1
                else:
                    session.add(src)
                    added_sources += 1
            if added_sources > 0 or updated_sources > 0:
                logger.info(f"Seeded sources: added {added_sources}, updated {updated_sources}.")
            else:
                logger.info("All sources are already up-to-date in the database.")
                
            # Deactivate sources that are no longer in our seeding list
            supported_names = {src.name for src in sources_to_add}
            deactivated_count = 0
            all_db_sources = session.query(Source).all()
            for db_src in all_db_sources:
                if db_src.name not in supported_names and db_src.active:
                    db_src.active = False
                    deactivated_count += 1
            if deactivated_count > 0:
                logger.info(f"Deactivated {deactivated_count} deprecated/broken sources.")

            # 2. Incremental Seed for Users
            added_users = 0
            for usr in users_to_add:
                exists = session.query(User).filter(User.email == usr.email).first()
                if not exists:
                    session.add(usr)
                    added_users += 1
            if added_users > 0:
                logger.info(f"Added {added_users} new users to the database.")
            else:
                logger.info("All users are already up-to-date in the database.")
                
            # The context manager automatically calls session.commit() on block exit.
            
    except Exception as e:
        logger.error(f"Seeding failed: {str(e)}")
        sys.exit(1)

def verify_data():
    """
    Demonstrates reading data using the context manager.
    """
    logger.info("Verifying seeded data...")
    try:
        with get_db_session() as session:
            # Query and list active sources
            active_sources = session.query(Source).filter(Source.active == True).all()
            logger.info("--- Active Sources ---")
            for src in active_sources:
                logger.info(f"- [{src.type.value}] {src.name} (RSS: {src.rss_url})")
                
            # Query and list users
            users = session.query(User).all()
            logger.info("--- Users ---")
            for user in users:
                logger.info(f"- {user.name} | Email: {user.email} | Role: {user.role.value}")
    except Exception as e:
        logger.error(f"Verification failed: {str(e)}")

if __name__ == "__main__":
    create_tables()
    seed_database()
    verify_data()
    logger.info("Database setup is complete and verified!")
