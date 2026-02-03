# src/auth.py
from __future__ import annotations

import sys
import streamlit as st
from src.db import ensure_users_file, has_admin_user, has_any_user, upsert_user, get_user_by_email, verify_password

# Password requirements
MIN_PASSWORD_LENGTH = 6


def is_logged_in() -> bool:
    return bool(st.session_state.get("auth_ok") is True and st.session_state.get("auth_email"))


def is_admin() -> bool:
    return (st.session_state.get("auth_role") == "admin") or (st.session_state.get("is_admin") is True)


def logout_button(label: str = "🚪 Cerrar sesión") -> None:
    if st.button(label, key="logout_button", use_container_width=True):
        for k in ["auth_ok", "auth_email", "auth_role", "is_admin"]:
            st.session_state.pop(k, None)
        st.rerun()


def _ensure_admin_from_secrets() -> None:
    """
    Check if there's an admin defined in Streamlit secrets.
    If yes and no users exist yet, auto-create the admin user.
    This provides a way to bootstrap the admin without relying on ephemeral file storage.
    
    In .streamlit/secrets.toml, add:
    [admin]
    email = "admin@example.com"
    password = "your-secure-password"
    """
    try:
        # Only auto-create if no users exist yet
        if has_any_user():
            return
        
        # Check if admin credentials are in secrets
        if hasattr(st, "secrets") and "admin" in st.secrets:
            admin_email = st.secrets["admin"].get("email", "").strip().lower()
            admin_password = st.secrets["admin"].get("password", "")
            
            if admin_email and "@" in admin_email and admin_password and len(admin_password) >= MIN_PASSWORD_LENGTH:
                # Auto-create admin from secrets
                upsert_user(admin_email, admin_password, role="admin")
                print(f"[INFO] Auto-created admin user from Streamlit secrets: {admin_email}", file=sys.stderr)
    except Exception as e:
        # Don't fail the app if secrets aren't configured
        print(f"[DEBUG] Could not auto-create admin from secrets: {e}", file=sys.stderr)


def _centered_card(width_ratio: float = 1.8):
    """
    Helper para centrar contenido en una 'card' (container con border).
    width_ratio: mientras más grande, más angosta la card (ej: 1.8–2.2).
    """
    left, mid, right = st.columns([1, width_ratio, 1], gap="large")
    with mid:
        return st.container(border=True)


def _setup_screen() -> None:
    # CSS específico para hacer el cuadro de login más pequeño y centrado
    st.markdown(
        """
        <style>
        /* Narrow the forms (login) and make them centered and squared */
        div[data-testid="stForm"] {
            width: 400px !important;
            margin: 0 auto !important;
            border-radius: 12px !important;
            padding: 24px !important;
        }
        /* Slightly larger title icon */
        .login-title-icon { font-size: 1.1rem; margin-right: 8px; vertical-align: middle; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    with _centered_card(3.5):
        st.markdown("## 🛠️ Crear usuario admin (primer arranque)")
        st.caption("Este paso se ejecuta solo cuando aún no existe ningún usuario.")

        with st.form("setup_admin"):
            email = st.text_input("Email admin").strip().lower()
            pwd = st.text_input("Contraseña", type="password")
            pwd2 = st.text_input("Repetir contraseña", type="password")
            ok = st.form_submit_button("Crear admin", use_container_width=True)

        if not ok:
            return

        if not email or "@" not in email:
            st.error("Email inválido.")
            return
        if not pwd or pwd != pwd2 or len(pwd) < MIN_PASSWORD_LENGTH:
            st.error(f"Contraseña inválida o no coincide (mínimo {MIN_PASSWORD_LENGTH}).")
            return

        upsert_user(email, pwd, role="admin")
        
        # Verify the user was created successfully
        if has_any_user():
            st.success("Admin creado. Ahora inicia sesión.")
        else:
            st.error("Error: No se pudo verificar la creación del admin. Revisa los logs.")
            return
        
        st.rerun()


def require_login() -> bool:
    ensure_users_file()
    
    # Check if admin credentials are in Streamlit secrets and auto-create if needed
    _ensure_admin_from_secrets()

    if is_logged_in():
        return True

    if not has_admin_user():
        _setup_screen()
        return False

    st.write("")
    with _centered_card(3.5):
        st.markdown("## 🔐 Iniciar sesión")

        with st.form("login_form"):
            email = st.text_input("Email").strip().lower()
            pwd = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Entrar", use_container_width=True)

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
