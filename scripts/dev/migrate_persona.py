"""
Migration script to add the UserPersona table to the existing database.
Run this once: python tmp/migrate_persona.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'infoagent.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if table already exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='userpersona'")
    if cursor.fetchone():
        print("✅ Table 'userpersona' already exists.")
        conn.close()
        return
    
    cursor.execute("""
        CREATE TABLE userpersona (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category VARCHAR DEFAULT 'instruction',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("CREATE INDEX idx_userpersona_category ON userpersona(category)")
    
    conn.commit()
    print("✅ Created 'userpersona' table successfully.")
    conn.close()

if __name__ == '__main__':
    migrate()
