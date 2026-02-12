# src/db.py
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
USERS_PATH = DATA_DIR / "users.json"
DB_PATH = DATA_DIR / "app.sqlite3"

# Guard flag to ensure tables are only initialized once per application lifecycle
_db_tables_initialized = False


# Database configuration - auto-detect environment
def _get_database_url():
    """Get database URL from Streamlit secrets (production) or use SQLite (local)."""
    try:
        import streamlit as st
        if "database" in st.secrets and "url" in st.secrets["database"]:
            return st.secrets["database"]["url"]
    except (ImportError, FileNotFoundError, KeyError):
        pass
    return None


def _is_postgres():
    """Check if using PostgreSQL."""
    url = _get_database_url()
    return url is not None and url.startswith("postgresql://")


def _execute_query(cursor, query: str, params: tuple = ()):
    """Execute query with appropriate placeholder syntax for database type."""
    if _is_postgres():
        # PostgreSQL uses %s placeholders
        pg_query = query.replace("?", "%s")
        cursor.execute(pg_query, params)
    else:
        # SQLite uses ? placeholders
        cursor.execute(query, params)


def _get_cursor(conn):
    """Get appropriate cursor for the database type."""
    if _is_postgres():
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _migrate_users_from_json() -> None:
    """
    Migrate users from JSON file to SQLite if the JSON file exists.
    After migration, rename the JSON file to .migrated as a backup.
    """
    if not USERS_PATH.exists():
        return
    
    try:
        # Read existing JSON data
        raw = USERS_PATH.read_text(encoding="utf-8").strip() or "{}"
        data = json.loads(raw)
        
        if not isinstance(data, dict) or not data:
            # Empty or invalid JSON, just rename it
            USERS_PATH.rename(USERS_PATH.with_suffix(".json.migrated"))
            print(f"[INFO] Renamed empty/invalid {USERS_PATH} to .migrated", file=sys.stderr)
            return
        
        # Check if users already exist in SQLite to avoid duplicate migration
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM users")
        count = cur.fetchone()["count"]
        
        if count > 0:
            # Users already in SQLite, just rename the JSON file
            conn.close()
            USERS_PATH.rename(USERS_PATH.with_suffix(".json.migrated"))
            print(f"[INFO] Users already in SQLite (count: {count}), renamed {USERS_PATH} to .migrated", file=sys.stderr)
            return
        
        # Migrate users to SQLite
        migrated_count = 0
        for email_key, user_data in data.items():
            if not isinstance(user_data, dict):
                continue
            
            email = _norm_email(email_key)
            role = user_data.get("role", "user")
            created_at = user_data.get("created_at", _now_iso())
            algo = user_data.get("algo", "pbkdf2_sha256")
            iterations = user_data.get("iterations", "200000")
            salt_b64 = user_data.get("salt_b64", "")
            hash_b64 = user_data.get("hash_b64", "")
            gpt_api_key = user_data.get("gpt_api_key")
            perplexity_api_key = user_data.get("perplexity_api_key")  # Include perplexity key
            
            # Skip invalid entries
            if not email or not salt_b64 or not hash_b64:
                print(f"[WARN] Skipping invalid user entry: {email_key}", file=sys.stderr)
                continue
            
            cur.execute("""
                INSERT OR REPLACE INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key, perplexity_api_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key, perplexity_api_key))
            migrated_count += 1
        
        conn.commit()
        
        # Rename JSON file to .migrated (after successful migration)
        USERS_PATH.rename(USERS_PATH.with_suffix(".json.migrated"))
        print(f"[SUCCESS] Migrated {migrated_count} users from JSON to SQLite, renamed file to .migrated", file=sys.stderr)
        
        conn.close()
        
    except Exception as e:
        print(f"[ERROR] Failed to migrate users from JSON: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        # Don't raise - allow the app to continue with empty users


def ensure_users_file() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # NOTE: Table initialization is now handled by init_db() at app startup
        # Removed _init_db_tables() call here to fix performance issue
        
        # Migration: Add perplexity_api_key column if it doesn't exist (for existing SQLite databases)
        if not _is_postgres():
            try:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT perplexity_api_key FROM users LIMIT 1")
                conn.close()
                print("[INFO] perplexity_api_key column already exists", file=sys.stderr)
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                print("[INFO] Adding perplexity_api_key column to users table", file=sys.stderr)
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("ALTER TABLE users ADD COLUMN perplexity_api_key TEXT")
                conn.commit()
                conn.close()
                print("[SUCCESS] perplexity_api_key column added successfully", file=sys.stderr)
        
        # Migrate from JSON if exists (SQLite only)
        if not _is_postgres():
            _migrate_users_from_json()
        
    except Exception as e:
        print(f"[ERROR] Error in ensure_users_file: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise


def load_users() -> Dict[str, Dict[str, Any]]:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        _execute_query(cur, "SELECT * FROM users", ())
        rows = cur.fetchall()
        conn.close()
        
        users = {}
        for row in rows:
            email = row["email"]
            users[email] = {
                "role": row["role"],
                "created_at": row["created_at"],
                "algo": row["algo"],
                "iterations": row["iterations"],
                "salt_b64": row["salt_b64"],
                "hash_b64": row["hash_b64"],
            }
            if row["gpt_api_key"]:
                users[email]["gpt_api_key"] = row["gpt_api_key"]
            try:
                if row["perplexity_api_key"]:
                    users[email]["perplexity_api_key"] = row["perplexity_api_key"]
            except (IndexError, KeyError):
                # Column doesn't exist yet (shouldn't happen after migration)
                pass
        
        return users
    except Exception as e:
        # Log the error for debugging, but return empty dict to allow app to continue
        print(f"Error loading users from database: {e}", file=sys.stderr)
        return {}


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        
        try:
            # Clear existing users
            _execute_query(cur, "DELETE FROM users", ())
            
            # Insert all users
            for email, user_data in users.items():
                email_n = _norm_email(email)
                role = user_data.get("role", "user")
                created_at = user_data.get("created_at", _now_iso())
                algo = user_data.get("algo", "pbkdf2_sha256")
                iterations = user_data.get("iterations", "200000")
                salt_b64 = user_data.get("salt_b64", "")
                hash_b64 = user_data.get("hash_b64", "")
                gpt_api_key = user_data.get("gpt_api_key")
                perplexity_api_key = user_data.get("perplexity_api_key")
                
                _execute_query(cur, """
                    INSERT INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key, perplexity_api_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (email_n, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key, perplexity_api_key))
            
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        print(f"Error saving users to database: {e}", file=sys.stderr)
        raise


def hash_password(password: str, *, salt_b64: Optional[str] = None, iterations: int = 200_000) -> Dict[str, str]:
    if salt_b64:
        salt = base64.b64decode(salt_b64.encode("utf-8"))
    else:
        salt = os.urandom(16)

    dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return {
        "algo": "pbkdf2_sha256",
        "iterations": str(iterations),
        "salt_b64": base64.b64encode(salt).decode("utf-8"),
        "hash_b64": base64.b64encode(dk).decode("utf-8"),
    }


def verify_password(password: str, meta: Dict[str, Any]) -> bool:
    try:
        if meta.get("algo") != "pbkdf2_sha256":
            return False
        iterations = int(meta.get("iterations", "200000"))
        salt_b64 = str(meta.get("salt_b64", ""))
        expected = str(meta.get("hash_b64", ""))
        computed = hash_password(password, salt_b64=salt_b64, iterations=iterations)["hash_b64"]
        return computed == expected
    except Exception:
        return False


def upsert_user(email: str, password: str, role: str = "user") -> Dict[str, Any]:
    email_n = _norm_email(email)
    ensure_users_file()
    
    meta = hash_password(password)
    created_at = _now_iso()
    
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        
        # Insert or update user, preserving gpt_api_key and perplexity_api_key if they exist
        _execute_query(cur, """
            INSERT INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key, perplexity_api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(email) DO UPDATE SET
                role = excluded.role,
                algo = excluded.algo,
                iterations = excluded.iterations,
                salt_b64 = excluded.salt_b64,
                hash_b64 = excluded.hash_b64,
                gpt_api_key = COALESCE(users.gpt_api_key, excluded.gpt_api_key),
                perplexity_api_key = COALESCE(users.perplexity_api_key, excluded.perplexity_api_key)
        """, (email_n, role, created_at, meta["algo"], meta["iterations"], meta["salt_b64"], meta["hash_b64"]))
        
        conn.commit()
        conn.close()
        
        return {"role": role, "created_at": created_at, **meta}
    except Exception as e:
        print(f"Error upserting user {email_n}: {e}", file=sys.stderr)
        raise


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    ensure_users_file()
    email_n = _norm_email(email)
    
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        _execute_query(cur, "SELECT * FROM users WHERE email = ?", (email_n,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return None
        
        # Convert to dict and filter out None values for optional fields
        user = {
            "role": row["role"],
            "created_at": row["created_at"],
            "algo": row["algo"],
            "iterations": row["iterations"],
            "salt_b64": row["salt_b64"],
            "hash_b64": row["hash_b64"],
        }
        
        # Only include optional fields if they have values
        # Handle both sqlite3.Row (dict-like) and psycopg2.RealDictRow
        try:
            gpt_key = row["gpt_api_key"]
            if gpt_key:
                user["gpt_api_key"] = gpt_key
        except (KeyError, IndexError):
            pass
            
        try:
            perplexity_key = row["perplexity_api_key"]
            if perplexity_key:
                user["perplexity_api_key"] = perplexity_key
        except (KeyError, IndexError):
            pass
        
        return user
    except Exception as e:
        print(f"Error getting user {email_n}: {e}", file=sys.stderr)
        return None


def update_user_gpt_api_key(email: str, api_key: str) -> None:
    """Update the GPT API key for a user."""
    email_n = _norm_email(email)
    ensure_users_file()
    
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        
        # Check if user exists
        _execute_query(cur, "SELECT email FROM users WHERE email = ?", (email_n,))
        if not cur.fetchone():
            conn.close()
            raise ValueError(f"User {email_n} not found")
        
        # Update the API key
        _execute_query(cur, "UPDATE users SET gpt_api_key = ? WHERE email = ?", (api_key, email_n))
        conn.commit()
        conn.close()
    except ValueError:
        raise
    except Exception as e:
        print(f"Error updating GPT API key for {email_n}: {e}", file=sys.stderr)
        raise


def get_user_gpt_api_key(email: str) -> Optional[str]:
    """Get the GPT API key for a user."""
    user = get_user_by_email(email)
    if user:
        return user.get("gpt_api_key")
    return None


def update_user_perplexity_api_key(email: str, api_key: str) -> None:
    """Update the Perplexity API key for a user."""
    email_n = _norm_email(email)
    ensure_users_file()
    
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        
        # Check if user exists
        _execute_query(cur, "SELECT email FROM users WHERE email = ?", (email_n,))
        if not cur.fetchone():
            conn.close()
            raise ValueError(f"User {email_n} not found")
        
        # Update the API key
        _execute_query(cur, "UPDATE users SET perplexity_api_key = ? WHERE email = ?", (api_key, email_n))
        conn.commit()
        conn.close()
    except ValueError:
        raise
    except Exception as e:
        print(f"Error updating Perplexity API key for {email_n}: {e}", file=sys.stderr)
        raise


def get_user_perplexity_api_key(email: str) -> Optional[str]:
    """Get the Perplexity API key for a user."""
    email_n = _norm_email(email)
    ensure_users_file()
    
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        _execute_query(cur, "SELECT perplexity_api_key FROM users WHERE email = ?", (email_n,))
        row = cur.fetchone()
        conn.close()
        return row["perplexity_api_key"] if row and row["perplexity_api_key"] else None
    except Exception as e:
        print(f"Error getting Perplexity API key for {email_n}: {e}", file=sys.stderr)
        return None


def has_any_user() -> bool:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        _execute_query(cur, "SELECT COUNT(*) as count FROM users", ())
        count = cur.fetchone()["count"]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"Error checking if any user exists: {e}", file=sys.stderr)
        return False


def has_admin_user() -> bool:
    """Check if there is at least one user with 'admin' role."""
    ensure_users_file()
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        _execute_query(cur, "SELECT COUNT(*) as count FROM users WHERE role = ?", ('admin',))
        count = cur.fetchone()["count"]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"Error checking if admin user exists: {e}", file=sys.stderr)
        return False


def get_conn():
    """Get database connection (PostgreSQL in production, SQLite locally)."""
    if _is_postgres():
        import psycopg2
        import psycopg2.extras
        
        url = _get_database_url()
        conn = psycopg2.connect(url)
        
        # Use RealDictCursor for dict-like row access (similar to sqlite3.Row)
        return conn
    else:
        # SQLite for local development
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def _init_db_tables() -> None:
    """Initialize all database tables (PostgreSQL or SQLite).
    
    This function uses a guard flag to ensure it only runs once per app lifecycle,
    preventing the performance issue of repeated table creation on every get_conn() call.
    """
    global _db_tables_initialized
    
    # Guard: Only initialize tables once
    if _db_tables_initialized:
        return
    
    conn = get_conn()
    cur = conn.cursor()
    
    is_pg = _is_postgres()
    
    # Auto-increment syntax differs between databases
    # SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
    # PostgreSQL: SERIAL PRIMARY KEY or BIGSERIAL PRIMARY KEY
    autoincrement = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    # Users table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            algo TEXT NOT NULL,
            iterations TEXT NOT NULL,
            salt_b64 TEXT NOT NULL,
            hash_b64 TEXT NOT NULL,
            gpt_api_key TEXT,
            perplexity_api_key TEXT
        )
    """)
    
    # Cache table (kv_cache) - used by cache_store.py
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS kv_cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            ttl_seconds INTEGER
        )
    """)
    
    # Blog posts table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS blog_posts (
            id {autoincrement},
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author_email TEXT NOT NULL,
            published_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            images_json TEXT,
            ticker TEXT
        )
    """)
    
    # Blog comments table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS blog_comments (
            id {autoincrement},
            post_id INTEGER NOT NULL,
            author_email TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES blog_posts(id) ON DELETE CASCADE
        )
    """)
    
    # Create index for blog post ticker lookup (if not exists)
    if is_pg:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_blog_posts_ticker 
            ON blog_posts(ticker) 
            WHERE ticker IS NOT NULL
        """)
    else:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_blog_posts_ticker 
            ON blog_posts(ticker) 
        """)
    
    conn.commit()
    conn.close()
    
    # Mark tables as initialized
    _db_tables_initialized = True
    print("[INFO] Database tables initialized successfully", file=sys.stderr)


def verify_database_integrity() -> bool:
    """
    Verify that the database schema is correct and accessible.
    Returns True if database is healthy, False otherwise.
    """
    try:
        conn = get_conn()
        cur = _get_cursor(conn)
        
        is_pg = _is_postgres()
        
        if is_pg:
            # PostgreSQL: Check if users table exists
            _execute_query(cur, """
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' AND tablename = ?
            """, ('users',))
            if not cur.fetchone():
                print("[ERROR] Users table does not exist", file=sys.stderr)
                conn.close()
                return False
            
            # For PostgreSQL, we'll just try to query the table
            _execute_query(cur, "SELECT COUNT(*) as count FROM users", ())
            count = cur.fetchone()["count"]
        else:
            # SQLite: Check users table exists
            _execute_query(cur, "SELECT name FROM sqlite_master WHERE type=? AND name=?", ('table', 'users'))
            if not cur.fetchone():
                print("[ERROR] Users table does not exist", file=sys.stderr)
                conn.close()
                return False
            
            # Check required columns exist (SQLite specific)
            cur.execute("PRAGMA table_info(users)")
            columns = {row["name"] for row in cur.fetchall()}
            required_columns = {"email", "role", "created_at", "algo", "iterations", "salt_b64", "hash_b64", "gpt_api_key", "perplexity_api_key"}
            
            missing_columns = required_columns - columns
            if missing_columns:
                print(f"[ERROR] Missing columns in users table: {missing_columns}", file=sys.stderr)
                conn.close()
                return False
            
            # Try to query users table
            _execute_query(cur, "SELECT COUNT(*) as count FROM users", ())
            count = cur.fetchone()["count"]
        
        print(f"[INFO] Database integrity check passed. User count: {count}", file=sys.stderr)
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"[ERROR] Database integrity check failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False


def init_db() -> None:
    # Debug: Print paths for troubleshooting on Streamlit Cloud
    print(f"[DEBUG] REPO_ROOT: {REPO_ROOT}", file=sys.stderr)
    print(f"[DEBUG] DATA_DIR: {DATA_DIR}", file=sys.stderr)
    print(f"[DEBUG] DB_PATH: {DB_PATH}", file=sys.stderr)
    print(f"[DEBUG] DB_PATH exists: {DB_PATH.exists()}", file=sys.stderr)
    print(f"[DEBUG] Using PostgreSQL: {_is_postgres()}", file=sys.stderr)
    
    # Initialize all database tables (runs once per app lifecycle)
    _init_db_tables()
    
    # Initialize user file and run migrations
    ensure_users_file()
    
    # Verify database integrity
    if not verify_database_integrity():
        print("[ERROR] Database integrity check failed. Please check logs.", file=sys.stderr)
    
    # Debug: Print user count after init
    try:
        users = load_users()
        user_count = len(users)
        admin_count = sum(1 for u in users.values() if u.get("role") == "admin")
        print(f"[DEBUG] User count after init: {user_count} (admins: {admin_count})", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Failed to load users after init: {e}", file=sys.stderr)
