# src/auth.py
from __future__ import annotations

import json
import streamlit as st

from .db import (
    USERS_PATH,
    ensure_users_file,
    get_user_by_email,
    has_any_user,
    hash_password,
    verify_password,
)

SESSION_KEY = "auth_ok"
SESSION_EMAIL = "auth_email"
SESSION_ROLE = "auth_role"

def is_admin() -> bool:
    return st.session_state.get(SESSION_ROLE, "") == "admin"

def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_KEY))


def current_user_email() -> str:
    return st.session_state.get(SESSION_EMAIL, "")


def logout() -> None:
    st.session_state[SESSION_KEY] = False
    st.session_state[SESSION_EMAIL] = ""
    st.session_state[SESSION_ROLE] = ""
    st.rerun()


def logout_button(label="Cerrar sesión"):
    if st.button(label, key="logout_button", use_container_width=True):
        logout()


def _setup_screen() -> None:
    """
    Setup NO persiste automáticamente en Streamlit Cloud.
    Por eso generamos el JSON y tú lo copias a data/users.json y lo commiteas.
    """
    st.markdown("## 🛠️ Configuración inicial (crear admin)")
    st.info(
        "No hay usuarios registrados todavía. "
        "Aquí puedes generar el contenido de `data/users.json` con un usuario admin.\n\n"
        "Después **copia el JSON generado** en `data/users.json`, haz commit y redeploy."
    )

    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input("Correo admin", value="cokedividendos@gmail.com")
    with col2:
        role = st.selectbox("Rol", ["admin", "user"], index=0)

    pw = st.text_input("Contraseña admin", type="password")

    if st.button("Generar users.json", type="primary"):
        if not email.strip() or not pw:
            st.error("Debes ingresar correo y contraseña.")
            return

        meta = hash_password(pw)
        payload = {
            email.strip().lower(): {
                "role": role,
                "created_at": "GENERATED_IN_APP",
                **meta,
            }
        }
        st.success("Listo. Copia este JSON y pégalo en `data/users.json` (y commitea).")
        st.code(json.dumps(payload, indent=2, ensure_ascii=False), language="json")
        st.caption(f"Ruta esperada: {USERS_PATH}")


def require_login() -> bool:
    """
    Devuelve True si el usuario está logueado. Si no, muestra UI de login/setup y devuelve False.
    """
    ensure_users_file()

    if is_logged_in():
        return True

    # Si no hay usuarios -> pantalla de setup
    if not has_any_user():
        _setup_screen()
        return False

    # Login normal
    st.markdown("## 🔐 Iniciar sesión")
    email = st.text_input("Correo", placeholder="tucorreo@gmail.com")
    password = st.text_input("Contraseña", type="password")

    if st.button("Entrar"):
        u = get_user_by_email(email)
        if not u:
            st.error("Usuario no autorizado.")
            return False
        if not verify_password(password, u):
            st.error("Contraseña incorrecta.")
            return False

        st.session_state[SESSION_KEY] = True
        st.session_state[SESSION_EMAIL] = email.strip().lower()
        st.session_state[SESSION_ROLE] = u.get("role", "user")
        st.rerun()

    return False
