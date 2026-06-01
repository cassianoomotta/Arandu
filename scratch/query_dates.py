import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import get_db_session
from database.models import News
from sqlalchemy import func

with get_db_session() as session:
    # Get range of created_at
    min_created, max_created = session.query(func.min(News.created_at), func.max(News.created_at)).first()
    print(f"News created_at range: {min_created} to {max_created}")
    
    # Get count by day
    by_day = session.query(func.date(News.created_at), func.count(News.id)).group_by(func.date(News.created_at)).all()
    print("News count by date:")
    for day, count in by_day:
        print(f"  {day}: {count} news")
        
    # Get count by relevance_score
    by_score = session.query(News.relevance_score, func.count(News.id)).group_by(News.relevance_score).all()
    print("News count by relevance score:")
    for score, count in by_score:
        print(f"  Score {score}: {count} news")
