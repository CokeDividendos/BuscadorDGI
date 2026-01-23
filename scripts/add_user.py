import bcrypt
from src.db import init_db, upsert_user

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

if __name__ == "__main__":
    init_db()
    email = input("Email: ").strip().lower()
    password = input("Password: ").strip()
    upsert_user(email=email, password_hash=hash_password(password), is_active=True)
    print("OK - usuario creado/actualizado.")
