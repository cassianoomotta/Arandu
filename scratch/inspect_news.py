import sqlite3
import json

db_path = "arandu.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get table information
cursor.execute("PRAGMA table_info(news)")
columns = [row[1] for row in cursor.fetchall()]
print("Columns in news table:", columns)

# Inspect first few records that have editorial_summary
cursor.execute("SELECT id, original_title, editorial_status, editorial_summary, ai_summary FROM news WHERE editorial_summary IS NOT NULL LIMIT 5")
rows = cursor.fetchall()
print(f"\nFound {len(rows)} rows with editorial_summary:")
for r in rows:
    news_id, title, status, summary, ai_sum = r
    print(f"ID: {news_id} | Status: {status} | Title: {title}")
    print(f"editorial_summary: {summary[:200] if summary else 'None'}")
    print(f"ai_summary: {ai_sum[:200] if ai_sum else 'None'}")
    print("-" * 50)

# Also check records where editorial_summary is null, maybe they have the 4 tabs inside ai_summary?
cursor.execute("SELECT id, original_title, editorial_status, ai_summary FROM news WHERE editorial_summary IS NULL LIMIT 5")
rows_null = cursor.fetchall()
print(f"\nFound {len(rows_null)} rows where editorial_summary is NULL:")
for r in rows_null:
    news_id, title, status, ai_sum = r
    print(f"ID: {news_id} | Status: {status} | Title: {title}")
    print(f"ai_summary: {ai_sum[:200] if ai_sum else 'None'}")
    print("-" * 50)

conn.close()
