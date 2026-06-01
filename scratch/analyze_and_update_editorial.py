import os
import psycopg2
from dotenv import load_dotenv
import json

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("DATABASE_URL not found in environment!")
    exit(1)

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Get all news that have a non-null editorial_summary
cur.execute("""
    SELECT id, original_title, translated_title, editorial_status, editorial_summary 
    FROM news 
    WHERE editorial_summary IS NOT NULL
""")
rows = cur.fetchall()

print(f"Total news with non-null editorial_summary: {len(rows)}")
print("-" * 80)

to_update = []
already_published = []
invalid_summary = []

for r in rows:
    news_id, orig_title, trans_title, status, summary_str = r
    title = trans_title or orig_title
    
    # Check if summary is valid JSON and contains all 4 keys
    try:
        summary_data = json.loads(summary_str)
        # Check for the 4 required keys
        required_keys = ['what_happened', 'why_it_matters', 'possible_impacts', 'key_points']
        has_all_keys = all(k in summary_data for k in required_keys)
        
        if has_all_keys:
            # Check if values are not empty
            what = summary_data.get('what_happened', '').strip()
            why = summary_data.get('why_it_matters', '').strip()
            impacts = summary_data.get('possible_impacts', '').strip()
            pts = summary_data.get('key_points', [])
            
            if what and why and impacts and isinstance(pts, list) and len(pts) > 0:
                if status == 'publicado':
                    already_published.append((news_id, title))
                else:
                    to_update.append((news_id, title, status))
            else:
                invalid_summary.append((news_id, title, "Some fields are empty or invalid"))
        else:
            missing = [k for k in required_keys if k not in summary_data]
            invalid_summary.append((news_id, title, f"Missing keys: {missing}"))
    except json.JSONDecodeError:
        invalid_summary.append((news_id, title, "Invalid JSON format"))

print(f"Already set to 'publicado' (Editorial: OK): {len(already_published)}")
print(f"Invalid executive summaries: {len(invalid_summary)}")
for inv in invalid_summary[:10]:
    print(f"  - ID: {inv[0]} | Title: {inv[1][:50]} | Reason: {inv[2]}")

print(f"\nTo be updated to 'publicado' (Editorial: OK): {len(to_update)}")
for item in to_update:
    print(f"  - ID: {item[0]} | Title: {item[1][:60]} | Current Status: {item[2]}")

# Perform update
if to_update:
    print("\nUpdating database...")
    ids_to_update = [item[0] for item in to_update]
    cur.execute("""
        UPDATE news 
        SET editorial_status = 'publicado', 
            updated_at = NOW() 
        WHERE id = ANY(%s)
    """, (ids_to_update,))
    conn.commit()
    print(f"Successfully updated {len(ids_to_update)} news items to 'publicado'.")
else:
    print("\nNo news items to update.")

cur.close()
conn.close()
