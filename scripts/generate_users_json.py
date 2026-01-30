# scripts/generate_users_json.py
import os
import json
import base64
from pathlib import Path
from hashlib import pbkdf2_hmac
from datetime import datetime, timezone

# CONFIG: email y contraseña que me proporcionaste
email = "cokedividendos@gmail.com"
password = "Admin01*"

iterations = 200000
salt = os.urandom(16)
dk = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)

user = {
    "role": "admin",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "algo": "pbkdf2_sha256",
    "iterations": str(iterations),
    "salt_b64": base64.b64encode(salt).decode("utf-8"),
    "hash_b64": base64.b64encode(dk).decode("utf-8"),
}

data_dir = Path("data")  # repo/data
data_dir.mkdir(parents=True, exist_ok=True)
path = data_dir / "users.json"

# Si ya existe y deseas mantener otros usuarios, lo fusiona
if path.exists():
    existing = json.loads(path.read_text(encoding="utf-8") or "{}")
else:
    existing = {}

existing[email] = user
path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
print("Wrote", path.resolve())
print("Ahora commitea data/users.json: git add data/users.json && git commit -m 'Agregar admin inicial (users.json)' && git push")
