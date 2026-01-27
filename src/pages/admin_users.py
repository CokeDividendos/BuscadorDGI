# src/pages/admin_users.py
from __future__ import annotations

import streamlit as st
from src.auth import is_admin
from src.db import load_users, upsert_user


def page_admin_users() -> None:
    if not is_admin():
        st.error("No autorizado.")
        return

        st.markdown("### ➕ Crear/Actualizar usuario")

    with st.form("create_user"):
        email = st.text_input("Email").strip().lower()
        pwd = st.text_input("Contraseña", type="password")
        role = st.selectbox("Rol", ["user", "admin"], index=0)
        ok = st.form_submit_button("Guardar")

    if ok:
        if not email or "@" not in email:
            st.error("Email inválido.")
            return
        if not pwd or len(pwd) < 6:
            st.error("Contraseña mínima 6 caracteres.")
            return
        upsert_user(email, pwd, role=role)
        st.success("Usuario guardado.")
        st.rerun()
    
    st.divider()
    
    st.markdown("## 👥 Admin - Usuarios")

    users = load_users()
    if users:
        st.caption("Usuarios existentes")
        for email, meta in users.items():
            st.write(f"- {email} ({meta.get('role','user')})")
    else:
        st.info("No hay usuarios aún (esto es raro si ya logueaste).")

    
   
