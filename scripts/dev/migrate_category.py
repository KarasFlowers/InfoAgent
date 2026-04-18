import sqlite3
import os

def migrate():
    db_path = "./infoagent.db"
    if not os.path.exists(db_path):
        print("Database not found, no migration needed.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Adding 'category' column to 'newsitem' table...")
        cursor.execute("ALTER TABLE newsitem ADD COLUMN category TEXT DEFAULT 'Uncategorized'")
        conn.commit()
        print("✅ Migration successful.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("ℹ️ Column 'category' already exists.")
        else:
            print(f"❌ Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
