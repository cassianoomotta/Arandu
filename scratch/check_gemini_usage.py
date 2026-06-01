import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("DATABASE_URL not found in environment!")
    exit(1)

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Get usage in past 24 hours
cur.execute("""
    SELECT COUNT(*) 
    FROM gemini_usage_log 
    WHERE called_at >= NOW() - INTERVAL '24 hours'
""")
count = cur.fetchone()[0]

print(f"Gemini API calls in the last 24 hours: {count} / 1500 limit")
conn.close()
