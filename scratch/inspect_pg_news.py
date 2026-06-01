import os
import psycopg2
from dotenv import load_dotenv
import json

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("DATABASE_URL not found in environment!")
    exit(1)

# Convert connection string if it starts with postgresql:// to pass to psycopg2
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Get all news that have a non-null editorial_summary
cur.execute("SELECT id, original_title, translated_title, editorial_status, editorial_summary FROM news WHERE editorial_summary IS NOT NULL")
rows = cur.fetchall()

print(f"Found {len(rows)} news with non-null editorial_summary:")
print("-" * 80)
for r in rows[:15]:
    news_id, orig_title, trans_title, status, summary = r
    title = trans_title or orig_title
    print(f"ID: {news_id} | Status: {status} | Title: {title[:60]}")
    try:
        data = json.loads(summary)
        print("Keys present in JSON:", list(data.keys()))
        print("JSON preview:", json.dumps(data, indent=2, ensure_ascii=False)[:300])
    except Exception as e:
        print("Failed to parse JSON. Content preview:", summary[:200])
    print("-" * 80)

# Check all news where editorial_status is NOT 'publicado' but editorial_summary is NOT NULL or matches the criteria
print("\nNews NOT published but with non-null editorial_summary:")
cur.execute("SELECT id, original_title, editorial_status, editorial_summary FROM news WHERE editorial_status != 'publicado' AND editorial_summary IS NOT NULL")
unpublished = cur.fetchall()
print(f"Found {len(unpublished)} rows:")
for r in unpublished:
    print(f"ID: {r[0]} | Status: {r[1]} | Title: {r[2][:60]}")

cur.close()
conn.close()
