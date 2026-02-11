# src/pages/api_keys.py
from __future__ import annotations

import streamlit as st

from src.db import (
    get_user_gpt_api_key,
    update_user_gpt_api_key,
    get_user_perplexity_api_key,
    update_user_perplexity_api_key,
)


def page_api_keys() -> None:
    """Display the API Keys management page."""
    
    user_email = st.session_state.get('auth_email', '')
    
    if not user_email:
        st.error("Error: No se pudo obtener el email del usuario")
        return
    
    st.markdown("## 🔑 Gestión de API Keys")
    st.caption("Configure sus claves de API para habilitar funcionalidades adicionales")
    
    st.divider()
    
    # OpenAI GPT Section
    st.markdown("### 🤖 OpenAI GPT")
    st.caption("Utilizada para generar resúmenes financieros automáticos de empresas")
    
    current_gpt_key = get_user_gpt_api_key(user_email)
    
    with st.form("gpt_api_key_form", clear_on_submit=False):
        gpt_key_input = st.text_input(
            "API Key de OpenAI GPT",
            value=current_gpt_key or "",
            type="password",
            placeholder="sk-...",
            help="Obtén tu API Key en: https://platform.openai.com/api-keys"
        )
        
        col1, col2 = st.columns([3, 1])
        with col2:
            submit_gpt = st.form_submit_button("💾 Guardar", use_container_width=True)
        
        if submit_gpt:
            if gpt_key_input != current_gpt_key:
                try:
                    update_user_gpt_api_key(user_email, gpt_key_input)
                    st.success("✅ API Key de GPT guardada correctamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar API Key: {e}")
            else:
                st.info("ℹ️ La API Key no ha cambiado")
    
    if current_gpt_key:
        suffix = current_gpt_key[-8:] if len(current_gpt_key) >= 8 else current_gpt_key[-4:]
        st.success(f"✅ API Key configurada (termina en: ...{suffix})")
    else:
        st.warning("⚠️ No has configurado tu API Key de GPT. Los resúmenes financieros no estarán disponibles.")
    
    st.markdown("**¿Cómo obtener tu API Key?**")
    st.markdown("1. Ve a [OpenAI Platform](https://platform.openai.com/api-keys)")
    st.markdown("2. Inicia sesión o crea una cuenta")
    st.markdown("3. Click en 'Create new secret key'")
    st.markdown("4. Copia la key y pégala arriba")
    
    st.divider()
    
    # Perplexity AI Section
    st.markdown("### 🔍 Perplexity AI")
    st.caption("Utilizada para análisis de noticias recientes y tendencias del mercado")
    
    current_perplexity_key = get_user_perplexity_api_key(user_email)
    
    with st.form("perplexity_api_key_form", clear_on_submit=False):
        perplexity_key_input = st.text_input(
            "API Key de Perplexity AI",
            value=current_perplexity_key or "",
            type="password",
            placeholder="pplx-...",
            help="Obtén tu API Key en: https://www.perplexity.ai/settings/api"
        )
        
        col1, col2 = st.columns([3, 1])
        with col2:
            submit_perplexity = st.form_submit_button("💾 Guardar", use_container_width=True)
        
        if submit_perplexity:
            if perplexity_key_input != current_perplexity_key:
                try:
                    update_user_perplexity_api_key(user_email, perplexity_key_input)
                    st.success("✅ API Key de Perplexity guardada correctamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar API Key: {e}")
            else:
                st.info("ℹ️ La API Key no ha cambiado")
    
    if current_perplexity_key:
        suffix = current_perplexity_key[-8:] if len(current_perplexity_key) >= 8 else current_perplexity_key[-4:]
        st.success(f"✅ API Key configurada (termina en: ...{suffix})")
    else:
        st.warning("⚠️ No has configurado tu API Key de Perplexity. El análisis de noticias no estará disponible.")
    
    st.markdown("**¿Cómo obtener tu API Key?**")
    st.markdown("1. Ve a [Perplexity Settings](https://www.perplexity.ai/settings/api)")
    st.markdown("2. Inicia sesión con tu cuenta Perplexity Pro")
    st.markdown("3. Click en 'Generate API Key'")
    st.markdown("4. Copia la key y pégala arriba")
    
    st.divider()
    
    # Info section
    st.info("""
    💡 **Nota sobre privacidad**: 
    Tus API Keys se almacenan de forma segura en la base de datos y solo tú puedes verlas o modificarlas.
    Nunca compartas tus API Keys con nadie.
    """)
    
    st.markdown("---")
    st.caption("Las API Keys son necesarias para acceder a servicios externos de IA. Los costos de uso corren por tu cuenta según los planes de cada servicio.")
