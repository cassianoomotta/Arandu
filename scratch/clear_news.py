import sqlite3

def clear_news_table():
    db_path = "arandu.db"
    print(f"Connecting to database {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check current news count
    cursor.execute("SELECT COUNT(*) FROM news")
    count_before = cursor.fetchone()[0]
    print(f"Current news articles in table: {count_before}")
    
    # Delete all records from news table
    cursor.execute("DELETE FROM news")
    conn.commit()
    
    # Check count after delete
    cursor.execute("SELECT COUNT(*) FROM news")
    count_after = cursor.fetchone()[0]
    print(f"News articles in table after deletion: {count_after}")
    
    conn.close()
    print("Database cleared successfully!")

if __name__ == "__main__":
    clear_news_table()
