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

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
USERS_PATH = DATA_DIR / "users.json"
DB_PATH = DATA_DIR / "app.sqlite3"


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
            print(f"[INFO] Users already in SQLite, renamed {USERS_PATH} to .migrated", file=sys.stderr)
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
            
            # Skip invalid entries
            if not email or not salt_b64 or not hash_b64:
                continue
            
            cur.execute("""
                INSERT OR REPLACE INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key))
            migrated_count += 1
        
        conn.commit()
        
        # Rename JSON file to .migrated (after successful migration)
        USERS_PATH.rename(USERS_PATH.with_suffix(".json.migrated"))
        print(f"[INFO] Migrated {migrated_count} users from JSON to SQLite, renamed file to .migrated", file=sys.stderr)
        
        conn.close()
        
    except Exception as e:
        print(f"[ERROR] Failed to migrate users from JSON: {e}", file=sys.stderr)
        # Don't raise - allow the app to continue with empty users


def ensure_users_file() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create users table if it doesn't exist
        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                algo TEXT NOT NULL,
                iterations TEXT NOT NULL,
                salt_b64 TEXT NOT NULL,
                hash_b64 TEXT NOT NULL,
                gpt_api_key TEXT
            )
        """)
        conn.commit()
        conn.close()
        
        # Migrate from JSON if exists
        _migrate_users_from_json()
        
    except Exception as e:
        print(f"Error in ensure_users_file: {e}", file=sys.stderr)
        raise


def load_users() -> Dict[str, Dict[str, Any]]:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users")
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
        
        return users
    except Exception as e:
        # Log the error for debugging, but return empty dict to allow app to continue
        print(f"Error loading users from SQLite: {e}", file=sys.stderr)
        return {}


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Use a transaction to ensure atomicity
        conn.execute("BEGIN TRANSACTION")
        
        try:
            # Clear existing users
            cur.execute("DELETE FROM users")
            
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
                
                cur.execute("""
                    INSERT INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (email_n, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key))
            
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        print(f"Error saving users to SQLite: {e}", file=sys.stderr)
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
        cur = conn.cursor()
        
        # Insert or update user, preserving gpt_api_key if it exists
        cur.execute("""
            INSERT INTO users (email, role, created_at, algo, iterations, salt_b64, hash_b64, gpt_api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(email) DO UPDATE SET
                role = excluded.role,
                algo = excluded.algo,
                iterations = excluded.iterations,
                salt_b64 = excluded.salt_b64,
                hash_b64 = excluded.hash_b64,
                gpt_api_key = COALESCE(users.gpt_api_key, excluded.gpt_api_key)
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
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email_n,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return None
        
        user = {
            "role": row["role"],
            "created_at": row["created_at"],
            "algo": row["algo"],
            "iterations": row["iterations"],
            "salt_b64": row["salt_b64"],
            "hash_b64": row["hash_b64"],
        }
        if row["gpt_api_key"]:
            user["gpt_api_key"] = row["gpt_api_key"]
        
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
        cur = conn.cursor()
        
        # Check if user exists
        cur.execute("SELECT email FROM users WHERE email = ?", (email_n,))
        if not cur.fetchone():
            conn.close()
            raise ValueError(f"User {email_n} not found")
        
        # Update the API key
        cur.execute("UPDATE users SET gpt_api_key = ? WHERE email = ?", (api_key, email_n))
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


def has_any_user() -> bool:
    ensure_users_file()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM users")
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
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'")
        count = cur.fetchone()["count"]
        conn.close()
        return count > 0
    except Exception as e:
        print(f"Error checking if admin user exists: {e}", file=sys.stderr)
        return False


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Tabla usada por cache_store.py
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv_cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            ttl_seconds INTEGER
        )
        """
    )
    # Tabla para blog posts
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author_email TEXT NOT NULL,
            published_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            images_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def init_db() -> None:
    # Debug: Print paths for troubleshooting on Streamlit Cloud
    print(f"[DEBUG] REPO_ROOT: {REPO_ROOT}", file=sys.stderr)
    print(f"[DEBUG] DATA_DIR: {DATA_DIR}", file=sys.stderr)
    print(f"[DEBUG] USERS_PATH: {USERS_PATH}", file=sys.stderr)
    print(f"[DEBUG] USERS_PATH exists: {USERS_PATH.exists()}", file=sys.stderr)
    
    ensure_users_file()
    _ = get_conn()
    
    # Debug: Print user count after init
    user_count = len(load_users())
    print(f"[DEBUG] User count after init: {user_count}", file=sys.stderr)
