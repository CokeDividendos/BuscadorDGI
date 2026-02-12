#!/usr/bin/env python3
"""
Migrate data from local SQLite to Neon PostgreSQL.
Run this ONCE after deploying the PostgreSQL changes.

Usage:
    python scripts/migrate_to_neon.py
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def migrate():
    import sqlite3
    import psycopg2
    import psycopg2.extras
    from src.db import _get_database_url, DB_PATH
    
    # Check if Neon URL is configured
    neon_url = _get_database_url()
    if not neon_url or not neon_url.startswith("postgresql://"):
        print("❌ Error: No PostgreSQL URL found in Streamlit secrets.")
        print("   Make sure you've configured st.secrets['database']['url']")
        return False
    
    if not DB_PATH.exists():
        print(f"❌ Error: SQLite database not found at {DB_PATH}")
        print("   Nothing to migrate.")
        return False
    
    print("🔄 Starting migration from SQLite to PostgreSQL...")
    print(f"   Source: {DB_PATH}")
    print(f"   Target: {neon_url[:50]}...")
    
    # Connect to both databases
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(neon_url)
    
    # Migrate each table
    tables = ["users", "kv_cache", "blog_posts", "blog_comments"]
    
    for table in tables:
        print(f"\n📦 Migrating table: {table}")
        
        # Get all rows from SQLite
        sqlite_cur = sqlite_conn.cursor()
        try:
            sqlite_cur.execute(f"SELECT * FROM {table}")
            rows = sqlite_cur.fetchall()
        except sqlite3.OperationalError as e:
            print(f"   ⏭️  Table {table} doesn't exist in SQLite, skipping... ({e})")
            continue
        
        if not rows:
            print(f"   ⏭️  No data in {table}, skipping...")
            continue
        
        # Get column names
        columns = [desc[0] for desc in sqlite_cur.description]
        
        # Insert into PostgreSQL
        pg_cur = pg_conn.cursor()
        
        # Build INSERT query
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)
        insert_query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        
        migrated = 0
        for row in rows:
            try:
                pg_cur.execute(insert_query, tuple(row))
                migrated += 1
            except Exception as e:
                print(f"   ⚠️  Warning: Failed to migrate row: {e}")
        
        pg_conn.commit()
        print(f"   ✅ Migrated {migrated}/{len(rows)} rows")
    
    # Update sequence counters for auto-increment columns (PostgreSQL only)
    print("\n🔧 Updating sequence counters...")
    pg_cur = pg_conn.cursor()
    
    for table in ["blog_posts", "blog_comments"]:
        try:
            pg_cur.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table}', 'id'), 
                              COALESCE((SELECT MAX(id) FROM {table}), 1), 
                              true)
            """)
            pg_conn.commit()
            print(f"   ✅ Updated sequence for {table}")
        except Exception as e:
            print(f"   ⚠️  Warning: Could not update sequence for {table}: {e}")
    
    sqlite_conn.close()
    pg_conn.close()
    
    print("\n✅ Migration completed successfully!")
    print("\n📌 Next steps:")
    print("   1. Verify data in Neon dashboard")
    print("   2. Deploy the updated code to Streamlit Cloud")
    print("   3. Test blog posts and user authentication")
    print(f"   4. Backup or delete local SQLite file: {DB_PATH}")
    
    return True

if __name__ == "__main__":
    try:
        success = migrate()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
