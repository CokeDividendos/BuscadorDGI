# src/pages/admin_users.py
from __future__ import annotations

import json
import streamlit as st
from src.auth import is_admin
from src.db import load_users, upsert_user


def page_admin_users() -> None:
    if not is_admin():
        st.error("No autorizado.")
        return

    st.markdown("## 👑 Admin · Usuarios")

    # ─────────────────────────────────────────────
    # ➕ Crear / Actualizar usuario (PRIMERO)
    # ─────────────────────────────────────────────
    st.markdown("### ✔️ Crear / Actualizar usuario")

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
        st.success("Usuario guardado correctamente en la base de datos.")
        st.divider()

        # --- Mostrar snippet para añadir a Streamlit Secrets (manual copy/paste) ---
        st.markdown("#### Guardar en Streamlit Secrets (opcional, para persistencia entre reinicios)")
        st.info(
            "No es posible que la app escriba automáticamente en Streamlit Secrets. "
            "Copia el siguiente bloque y pégalo en Settings → Secrets de tu app en Streamlit Cloud."
        )

        # Generar snippet TOML con la sección [[users]]
        toml_snippet = f'''[[users]]
email = "{email}"
password = "{pwd}"
role = "{role}"
'''
        st.code(toml_snippet, language="toml")
        st.caption("Si ya tienes otros users definidos en Secrets, añade este bloque al final (cada usuario necesita su [[users]]).")

        st.markdown(
            "**Instrucciones rápidas:**\n\n"
            "1) Abre Settings → Secrets en Streamlit Cloud; \n"
            "2) Pega o añade el bloque anterior al final del archivo; \n"
            "3) Guarda los Secrets; \n"
            "4) Vuelve aquí y pulsa el botón 'He pegado el bloque en Secrets y quiero recargar la app' para forzar recarga/importación."
        )

        # Botón para recargar la app una vez el admin haya copiado y pegado el snippet en Secrets
        if st.button("He pegado el bloque en Secrets y quiero recargar la app"):
            st.experimental_rerun()

        st.divider()

    st.divider()

    # ─────────────────────────────────────────────
    # 👥 Usuarios existentes (DESPUÉS)
    # ─────────────────────────────────────────────
    st.markdown("### 📄 Usuarios existentes")

    users = load_users()

    if users:
        for email, meta in users.items():
            st.write(f"- **{email}** ({meta.get('role', 'user')})")

        st.divider()

        # Visualización JSON
        st.caption("Vista completa (JSON)")
        st.json(users)

        # Descarga del archivo
        st.download_button(
            label="⬇️ Descargar users.json",
            data=json.dumps(users, indent=2, ensure_ascii=False),
            file_name="users.json",
            mime="application/json",
            use_container_width=True,
        )
    else:
        st.info("No hay usuarios registrados.")
