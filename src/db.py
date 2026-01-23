# src/db.py
from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Any, Dict, Optional


# Repo root = .../src/.. (porque este archivo es src/db.py)
REPO_ROOT = Path(__file__).resolve().parents[1]
USERS_PATH = REPO_ROOT / "data" / "users.json"

# SQLite path (absoluto, para evitar problemas de cwd en deploy)
_DB_PATH = REPO_ROOT / "data" / "app.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def ensure_users_file() -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not USERS_PATH.exists():
        USERS_PATH.write_text("{}", encoding="utf-8")


def load_users() -> Dict[str, Dict[str, Any]]:
    ensure_users_file()
    try:
        raw = USERS_PATH.read_text(encoding="utf-8").strip() or "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                out[_norm_email(k)] = v
        return out
    except Exception:
        return {}


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    """
    OJO: En Streamlit Cloud, escribir archivos NO garantiza persistencia entre deploys.
    Este método sirve para uso local. En producción, debes commitear data/users.json.
    """
    ensure_users_file()
    USERS_PATH.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def hash_password(password: str, *, salt_b64: Optional[str] = None, iterations: int = 200_000) -> Dict[str, str]:
    """
    PBKDF2-HMAC-SHA256 (stdlib, sin bcrypt).
    Retorna dict con salt/hash base64.
    """
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
    users = load_users()
    meta = hash_password(password)
    users[email_n] = {
        "role": role,
        "created_at": _now_iso(),
        **meta,
    }
    save_users(users)
    return users[email_n]


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    email_n = _norm_email(email)
    users = load_users()
    return users.get(email_n)


def has_any_user() -> bool:
    users = load_users()
    return len(users) > 0


def get_conn() -> sqlite3.Connection:
    """
    Devuelve una conexión SQLite lista para uso concurrente en Streamlit Cloud.
    - WAL para mejor concurrencia (lecturas + escrituras).
    - busy_timeout + timeout para reducir "database is locked".
    """
    (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(_DB_PATH),
        check_same_thread=False,
        timeout=30,  # más tolerante a locks
    )
    conn.row_factory = sqlite3.Row

    # PRAGMAs para concurrencia y performance segura
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA busy_timeout=30000;")  # 30s
    except Exception:
        pass

    # Tabla cache legacy (si alguna parte la usa)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            expires_at INTEGER
        )
        """
    )

    # Tabla kv_cache (la que usa src/services/cache_store.py)
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

    conn.commit()
    return conn


def init_db() -> None:
    """
    Asegura el storage de usuarios y el SQLite.
    """
    ensure_users_file()
    conn = get_conn()
    conn.close()
