import sqlite3
import json

conn = sqlite3.connect('arandu.db')
cursor = conn.cursor()

# Get table list
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [r[0] for r in cursor.fetchall()]
print("Tables in DB:", tables)

# Get count of news
cursor.execute("SELECT COUNT(*) FROM news;")
count = cursor.fetchone()[0]
print("Total news in news table:", count)

# Get count by editorial_status
cursor.execute("SELECT editorial_status, COUNT(*) FROM news GROUP BY editorial_status;")
status_counts = cursor.fetchall()
print("News by editorial_status:", status_counts)

# Get some recent news
cursor.execute("SELECT id, original_title, translated_title, relevance_score, editorial_status, created_at FROM news ORDER BY id DESC LIMIT 10;")
recent_news = cursor.fetchall()
print("\nRecent news:")
for row in recent_news:
    print(f"ID: {row[0]} | Title: {row[1]} | Translated: {row[2]} | Score: {row[3]} | Status: {row[4]} | Created: {row[5]}")

conn.close()
