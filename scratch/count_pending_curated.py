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

# Count curated articles by status
cur.execute("""
    SELECT COALESCE(editorial_status, 'None'), COUNT(*) 
    FROM news 
    WHERE is_curated = TRUE 
    GROUP BY COALESCE(editorial_status, 'None')
""")
rows = cur.fetchall()

print("Curated news count by editorial_status in PostgreSQL database:")
for r in rows:
    print(f"Status: {r[0]} | Count: {r[1]}")

conn.close()
