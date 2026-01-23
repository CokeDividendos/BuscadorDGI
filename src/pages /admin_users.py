import json
import streamlit as st

from src.db import load_users, hash_password, USERS_PATH
from src.auth import is_admin


def page_admin_users():
    st.title("👑 Admin · Usuarios")

    if not is_admin():
        st.error("No autorizado.")
        st.stop()

    users = load_users()

    st.subheader("Usuarios actuales")
    if not users:
        st.info("No hay usuarios aún.")
    else:
        st.dataframe(
            [{"email": k, "role": v.get("role"), "created_at": v.get("created_at")} for k, v in users.items()],
            use_container_width=True,
        )

    st.divider()
    st.subheader("Agregar usuario (genera JSON para commitear)")

    email = st.text_input("Email nuevo usuario")
    role = st.selectbox("Rol", ["user", "admin"], index=0)
    pw = st.text_input("Contraseña temporal", type="password")

    if st.button("Generar JSON actualizado", type="primary"):
        if not email.strip() or not pw:
            st.error("Falta email o contraseña.")
            return

        email_n = email.strip().lower()
        users[email_n] = {
            "role": role,
            "created_at": "GENERATED_IN_APP",
            **hash_password(pw),
        }

        st.success("Listo. Copia este JSON y pégalo en `data/users.json`, commitea y redeploy.")
        st.caption(f"Ruta: {USERS_PATH}")
        st.code(json.dumps(users, indent=2, ensure_ascii=False), language="json")
