# src/pages/blogs.py
from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from typing import Optional

import streamlit as st
from PIL import Image

from src.auth import is_admin
from src.services.blog import (
    create_blog_post,
    delete_blog_post,
    get_blog_post,
    list_blog_posts,
    update_blog_post,
)


def _format_date(iso_date: str) -> str:
    """Format ISO date to a more readable format."""
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso_date


def _image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to base64 string."""
    buffered = BytesIO()
    image.save(buffered, format=format)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/{format.lower()};base64,{img_str}"


def _render_blog_post_card(post: dict, show_admin_actions: bool = False) -> None:
    """Render a single blog post card."""
    with st.container(border=True):
        st.markdown(f"### {post['title']}")
        st.caption(f"Publicado por **{post['author_email']}** el {_format_date(post['published_date'])}")
        
        # Show first 200 characters as preview
        preview = post['content'][:200] + "..." if len(post['content']) > 200 else post['content']
        st.markdown(preview)
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Leer más", key=f"read_{post['id']}", use_container_width=True):
                st.session_state["selected_blog_post"] = post['id']
                st.session_state["blog_view"] = "detail"
                st.rerun()
        
        if show_admin_actions:
            with col2:
                if st.button("✏️ Editar", key=f"edit_{post['id']}", use_container_width=True):
                    st.session_state["editing_blog_post"] = post['id']
                    st.session_state["blog_view"] = "edit"
                    st.rerun()


def _render_blog_detail(post_id: int) -> None:
    """Render full blog post detail."""
    post = get_blog_post(post_id)
    
    if not post:
        st.error("Post no encontrado.")
        if st.button("← Volver a la lista"):
            st.session_state["blog_view"] = "list"
            st.session_state.pop("selected_blog_post", None)
            st.rerun()
        return
    
    # Back button
    if st.button("← Volver a la lista"):
        st.session_state["blog_view"] = "list"
        st.session_state.pop("selected_blog_post", None)
        st.rerun()
    
    st.markdown(f"# {post['title']}")
    st.caption(f"Publicado por **{post['author_email']}** el {_format_date(post['published_date'])}")
    
    if post.get('updated_at') != post.get('created_at'):
        st.caption(f"_Última actualización: {_format_date(post['updated_at'])}_")
    
    st.divider()
    
    # Render content
    st.markdown(post['content'])
    
    # Render images if any
    if post.get('images'):
        st.divider()
        st.markdown("### Imágenes")
        for idx, img_data in enumerate(post['images']):
            if img_data.get('data'):
                st.image(img_data['data'], caption=img_data.get('caption', ''), use_container_width=True)


def _render_blog_editor(post_id: Optional[int] = None) -> None:
    """Render blog post editor (create or edit)."""
    is_edit = post_id is not None
    post = get_blog_post(post_id) if is_edit else None
    
    if is_edit and not post:
        st.error("Post no encontrado.")
        if st.button("← Volver"):
            st.session_state["blog_view"] = "list"
            st.session_state.pop("editing_blog_post", None)
            st.rerun()
        return
    
    # Back button
    if st.button("← Cancelar"):
        st.session_state["blog_view"] = "list"
        st.session_state.pop("editing_blog_post", None)
        st.rerun()
    
    st.markdown(f"## {'Editar' if is_edit else 'Crear'} artículo")
    
    with st.form("blog_editor_form"):
        title = st.text_input(
            "Título del artículo",
            value=post['title'] if post else "",
            max_chars=200
        )
        
        content = st.text_area(
            "Contenido (soporta Markdown)",
            value=post['content'] if post else "",
            height=400,
            help="Puedes usar formato Markdown: **negrita**, *cursiva*, # títulos, etc."
        )
        
        st.markdown("### Imágenes")
        uploaded_files = st.file_uploader(
            "Adjuntar imágenes (opcional)",
            type=["png", "jpg", "jpeg", "gif"],
            accept_multiple_files=True,
            help="Selecciona una o más imágenes para adjuntar al post"
        )
        
        # Image captions
        image_captions = {}
        if uploaded_files:
            st.markdown("**Descripciones de las imágenes:**")
            for idx, file in enumerate(uploaded_files):
                image_captions[file.name] = st.text_input(
                    f"Descripción para {file.name}",
                    key=f"caption_{idx}",
                    max_chars=200
                )
        
        submitted = st.form_submit_button(
            "💾 " + ("Actualizar artículo" if is_edit else "Publicar artículo"),
            use_container_width=True
        )
        
        if submitted:
            # Validation
            if not title or not title.strip():
                st.error("El título es obligatorio.")
                st.stop()
            
            if not content or not content.strip():
                st.error("El contenido es obligatorio.")
                st.stop()
            
            # Process images
            images = []
            if uploaded_files:
                for file in uploaded_files:
                    try:
                        img = Image.open(file)
                        img_base64 = _image_to_base64(img)
                        images.append({
                            "data": img_base64,
                            "caption": image_captions.get(file.name, ""),
                            "filename": file.name
                        })
                    except Exception as e:
                        st.warning(f"No se pudo procesar la imagen {file.name}: {e}")
            
            # Create or update post
            try:
                if is_edit:
                    success = update_blog_post(
                        post_id=post_id,
                        title=title.strip(),
                        content=content.strip(),
                        images=images if uploaded_files else None
                    )
                    if success:
                        st.success("✓ Artículo actualizado correctamente")
                        st.session_state["blog_view"] = "list"
                        st.session_state.pop("editing_blog_post", None)
                        st.rerun()
                    else:
                        st.error("Error al actualizar el artículo")
                else:
                    author_email = st.session_state.get('auth_email', '')
                    post_id = create_blog_post(
                        title=title.strip(),
                        content=content.strip(),
                        author_email=author_email,
                        images=images
                    )
                    st.success(f"✓ Artículo publicado correctamente (ID: {post_id})")
                    st.session_state["blog_view"] = "list"
                    st.rerun()
            except Exception as e:
                st.error(f"Error al guardar el artículo: {e}")


def _render_blog_list(admin: bool) -> None:
    """Render list of blog posts."""
    posts = list_blog_posts()
    
    if admin:
        st.markdown("## 📝 Gestión de artículos")
        
        if st.button("➕ Crear nuevo artículo", use_container_width=True):
            st.session_state["blog_view"] = "create"
            st.rerun()
        
        st.divider()
    else:
        st.markdown("## 📚 Blogs")
    
    if not posts:
        st.info("No hay artículos publicados aún." if not admin else "No hay artículos. ¡Crea el primero!")
        return
    
    # Display posts
    for post in posts:
        _render_blog_post_card(post, show_admin_actions=admin)


def page_blogs() -> None:
    """Main blog page handler."""
    admin = is_admin()
    
    # Initialize blog view state
    if "blog_view" not in st.session_state:
        st.session_state["blog_view"] = "list"
    
    current_view = st.session_state.get("blog_view", "list")
    
    # Route to appropriate view
    if current_view == "list":
        _render_blog_list(admin)
    elif current_view == "detail":
        post_id = st.session_state.get("selected_blog_post")
        if post_id:
            _render_blog_detail(post_id)
        else:
            st.session_state["blog_view"] = "list"
            st.rerun()
    elif current_view == "create" and admin:
        _render_blog_editor()
    elif current_view == "edit" and admin:
        post_id = st.session_state.get("editing_blog_post")
        if post_id:
            _render_blog_editor(post_id)
        else:
            st.session_state["blog_view"] = "list"
            st.rerun()
    else:
        # Invalid view or non-admin trying to access admin views
        st.session_state["blog_view"] = "list"
        st.rerun()
