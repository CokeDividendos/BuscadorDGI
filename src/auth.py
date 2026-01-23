# src/auth.py
from __future__ import annotations

import streamlit as st
from src.db import ensure_users_file, has_any_user, upsert_user, get_user_by_email, verify_password

def is_logged_in() -> bool:
    return bool(st.session_state.get("auth_ok") is True and st.session_state.get("auth_email"))

def is_admin() -> bool:
    return (st.session_state.get("auth_role") == "admin") or (st.session_state.get("is_admin") is True)

def logout_button() -> None:
    if st.button("🚪 Cerrar sesión", key="logout_button", use_container_width=True):
        for k in ["auth_ok", "auth_email", "auth_role", "is_admin"]:
            st.session_state.pop(k, None)
        st.rerun()

def _setup_screen() -> None:
    st.markdown("## 🛠️ Crear usuario admin (primer arranque)")
    with st.form("setup_admin"):
        email = st.text_input("Email admin").strip().lower()
        pwd = st.text_input("Contraseña", type="password")
        pwd2 = st.text_input("Repetir contraseña", type="password")
        ok = st.form_submit_button("Crear admin")
    if not ok:
        return
    if not email or "@" not in email:
        st.error("Email inválido.")
        return
    if not pwd or pwd != pwd2 or len(pwd) < 6:
        st.error("Contraseña inválida o no coincide (mínimo 6).")
        return
    upsert_user(email, pwd, role="admin")
    st.success("Admin creado. Ahora inicia sesión.")
    st.rerun()

def require_login() -> bool:
    ensure_users_file()

    if is_logged_in():
        return True

    if not has_any_user():
        _setup_screen()
        return False

    st.markdown("## 🔐 Iniciar sesión")
    with st.form("login_form"):
        email = st.text_input("Email").strip().lower()
        pwd = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Entrar")

    if not submit:
        return False

    u = get_user_by_email(email)
    if not u or not verify_password(pwd, u):
        st.error("Credenciales incorrectas.")
        return False

    st.session_state["auth_ok"] = True
    st.session_state["auth_email"] = email
    st.session_state["auth_role"] = u.get("role", "user")
    st.session_state["is_admin"] = (u.get("role") == "admin")
    st.rerun()
    return True
