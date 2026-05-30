import sqlite3
conn = sqlite3.connect('arandu.db')
cur = conn.cursor()
cur.execute("""
    SELECT id, translated_title, original_title, relevance_score, 
           editorial_status, send_status, category, source_id, created_at, is_curated
    FROM news 
    ORDER BY created_at DESC 
    LIMIT 50
""")
rows = cur.fetchall()
print(f"{'ID':>4} | {'Score':>5} | {'Edit':>12} | {'Send':>9} | {'Cat':>20} | {'Curated':>7} | Title")
print("-" * 140)
for r in rows:
    title = (r[1] or r[2] or "")[:70]
    score = r[3] if r[3] is not None else "N/A"
    edit_status = r[4] or "N/A"
    send_status = r[5] or "N/A"
    cat = (r[6] or "N/A")[:20]
    curated = r[9]
    print(f"{r[0]:>4} | {str(score):>5} | {edit_status:>12} | {send_status:>9} | {cat:>20} | {str(curated):>7} | {title}")

# Now check sources
print("\n\n=== ACTIVE SOURCES ===")
cur.execute("SELECT id, name, type, active FROM sources WHERE active = 1")
sources = cur.fetchall()
for s in sources:
    print(f"  ID:{s[0]} | Name:{s[1]} | Type:{s[2]} | Active:{s[3]}")

# Count articles by editorial status
print("\n=== ARTICLE COUNTS BY EDITORIAL STATUS ===")
cur.execute("SELECT editorial_status, COUNT(*) FROM news GROUP BY editorial_status")
for row in cur.fetchall():
    print(f"  {row[0] or 'NULL'}: {row[1]}")

# Count articles today
print("\n=== ARTICLES CREATED TODAY ===")
cur.execute("SELECT COUNT(*) FROM news WHERE date(created_at) = date('now')")
today_count = cur.fetchone()[0]
print(f"  Total today: {today_count}")

# Show today's articles with scores
print("\n=== TODAY'S ARTICLES DETAIL ===")
cur.execute("""
    SELECT n.id, n.translated_title, n.original_title, n.relevance_score, 
           n.editorial_status, n.send_status, n.category, s.name as source_name, n.is_curated
    FROM news n
    LEFT JOIN sources s ON n.source_id = s.id
    WHERE date(n.created_at) = date('now')
    ORDER BY n.relevance_score DESC
""")
today_rows = cur.fetchall()
print(f"{'ID':>4} | {'Score':>5} | {'Edit':>12} | {'Send':>9} | {'Source':>25} | Title")
print("-" * 160)
for r in today_rows:
    title = (r[1] or r[2] or "")[:65]
    score = r[3] if r[3] is not None else "N/A"
    edit_status = r[4] or "N/A"
    send_status = r[5] or "N/A"
    source = (r[7] or "N/A")[:25]
    print(f"{r[0]:>4} | {str(score):>5} | {edit_status:>12} | {send_status:>9} | {source:>25} | {title}")

conn.close()
