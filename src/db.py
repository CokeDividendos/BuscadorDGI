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

REPO_ROOT = Path(__file__).resolve().parents[1]

# Primary runtime data dir (escribible en la mayoría de entornos)
DATA_DIR = Path.cwd() / "data"
USERS_PATH = DATA_DIR / "users.json"
DB_PATH = DATA_DIR / "app.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def ensure_users_file() -> None:
    """
    Intenta crear users.json en DATA_DIR (runtime). Si no es posible,
    intenta crear en REPO_ROOT/data como fallback.
    """
    global USERS_PATH
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not USERS_PATH.exists():
            USERS_PATH.write_text("{}", encoding="utf-8")
    except Exception:
        # Fallback a carpeta del repo (por si cwd no es escribible)
        try:
            repo_data = REPO_ROOT / "data"
            repo_data.mkdir(parents=True, exist_ok=True)
            alt_path = repo_data / "users.json"
            if not alt_path.exists():
                alt_path.write_text("{}", encoding="utf-8")
            # Ajustar USERS_PATH a la ruta alterna para que las posteriores lecturas/escrituras la usen
            USERS_PATH = alt_path
        except Exception:
            # Si falla el fallback, dejamos que las funciones que leen usuarios manejen la ausencia.
            return


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
    ensure_users_file()
    USERS_PATH.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


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
    users = load_users()
    meta = hash_password(password)
    users[email_n] = {"role": role, "created_at": _now_iso(), **meta}
    save_users(users)
    return users[email_n]


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    users = load_users()
    return users.get(_norm_email(email))


def has_any_user() -> bool:
    return len(load_users()) > 0


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
    conn.commit()
    return conn


def init_db() -> None:
    """
    Inicializa lo mínimo necesario: archivo de usuarios y la BD sqlite (cache).
    """
    ensure_users_file()
    _ = get_conn()
