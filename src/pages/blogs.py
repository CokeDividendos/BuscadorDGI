# src/pages/blogs.py
from __future__ import annotations

import base64
import re
from datetime import datetime
from io import BytesIO
from typing import Optional

import streamlit as st
from PIL import Image

from src.auth import is_admin, is_logged_in
from src.services.blog import (
    create_blog_post,
    delete_blog_post,
    get_blog_post,
    list_blog_posts,
    update_blog_post,
)
from src.services.blog_comments import (
    create_comment,
    delete_comment,
    get_comments_by_post,
    count_comments,
)


def _format_date(iso_date: str) -> str:
    """Format ISO date to a more readable format."""
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso_date


def _image_to_base64(image: Image.Image, image_format: str = "PNG") -> str:
    """Convert PIL Image to base64 string."""
    buffered = BytesIO()
    image.save(buffered, format=image_format)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/{image_format.lower()};base64,{img_str}"


def _render_blog_post_card(post: dict, show_admin_actions: bool = False) -> None:
    """Render a single blog post card."""
    with st.container(border=True):
        st.markdown(f"### {post['title']}")
        
        # Display ticker if present
        ticker_badge = f" `{post['ticker']}`" if post.get('ticker') else ""
        st.caption(f"Publicado por **{post['author_email']}** el {_format_date(post['published_date'])}{ticker_badge}")
        
        # Show comment count
        num_comments = count_comments(post['id'])
        if num_comments > 0:
            st.caption(f"💬 {num_comments} comentario{'s' if num_comments != 1 else ''}")
        
        # Show first 200 characters as preview
        preview = post['content'][:200] + "..." if len(post['content']) > 200 else post['content']
        st.markdown(preview)
        
        if show_admin_actions:
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Leer más", key=f"read_{post['id']}", use_container_width=True):
                    st.session_state["selected_blog_post"] = post['id']
                    st.session_state["blog_view"] = "detail"
                    st.rerun()
            with col2:
                if st.button("✏️ Editar", key=f"edit_{post['id']}", use_container_width=True):
                    st.session_state["editing_blog_post"] = post['id']
                    st.session_state["blog_view"] = "edit"
                    st.rerun()
            with col3:
                if st.button("🗑️ Eliminar", key=f"delete_{post['id']}", use_container_width=True):
                    st.session_state["confirm_delete_post"] = post['id']
                    st.rerun()
        else:
            if st.button("Leer más", key=f"read_{post['id']}", use_container_width=True):
                st.session_state["selected_blog_post"] = post['id']
                st.session_state["blog_view"] = "detail"
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
    
    # Admin actions at the top
    if is_admin():
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            if st.button("← Volver a la lista"):
                st.session_state["blog_view"] = "list"
                st.session_state.pop("selected_blog_post", None)
                st.rerun()
        with col2:
            if st.button("✏️ Editar"):
                st.session_state["editing_blog_post"] = post_id
                st.session_state["blog_view"] = "edit"
                st.rerun()
        with col3:
            if st.button("🗑️ Eliminar"):
                st.session_state["confirm_delete_post"] = post_id
                st.session_state["blog_view"] = "list"
                st.rerun()
    else:
        # Regular back button for non-admin
        if st.button("← Volver a la lista"):
            st.session_state["blog_view"] = "list"
            st.session_state.pop("selected_blog_post", None)
            st.rerun()
    
    st.markdown(f"# {post['title']}")
    
    # Display ticker if present
    ticker_badge = f" `{post['ticker']}`" if post.get('ticker') else ""
    st.caption(f"Publicado por **{post['author_email']}** el {_format_date(post['published_date'])}{ticker_badge}")
    
    if post.get('updated_at') != post.get('created_at'):
        st.caption(f"_Última actualización: {_format_date(post['updated_at'])}_")
    
    st.divider()
    
    # Render content (with embedded images)
    st.markdown(post['content'], unsafe_allow_html=True)
    
    # Only show old-style images if they exist and content doesn't have embedded images
    # This maintains backward compatibility
    if post.get('images') and 'data:image' not in post['content']:
        st.divider()
        st.markdown("### Imágenes")
        for idx, img_data in enumerate(post['images']):
            if img_data.get('data'):
                st.image(img_data['data'], caption=img_data.get('caption', ''), use_container_width=True)
    
    # Comments section
    st.divider()
    st.markdown("## 💬 Comentarios")
    
    comments = get_comments_by_post(post_id)
    comment_count = len(comments)
    
    st.caption(f"{comment_count} comentario{'s' if comment_count != 1 else ''}")
    
    # Display existing comments
    if comments:
        for comment in comments:
            with st.container(border=True):
                st.markdown(f"**{comment['author_email']}** · {_format_date(comment['created_at'])}")
                st.markdown(comment['content'])
                
                # Delete button (only for admin or comment author)
                current_user = st.session_state.get('auth_email', '')
                if is_admin() or current_user == comment['author_email']:
                    if st.button("🗑️ Eliminar", key=f"delete_comment_{comment['id']}"):
                        if delete_comment(comment['id']):
                            st.success("Comentario eliminado")
                            st.rerun()
                        else:
                            st.error("Error al eliminar comentario")
    
    # New comment form (only for logged-in users)
    if is_logged_in():
        st.markdown("### ✍️ Escribe un comentario")
        with st.form(f"new_comment_form_{post_id}"):
            comment_content = st.text_area(
                "Tu comentario (soporta Markdown)",
                height=150,
                help="Puedes usar formato Markdown: **negrita**, *cursiva*, etc."
            )
            
            submit_comment = st.form_submit_button("💬 Publicar comentario", use_container_width=True)
            
            if submit_comment:
                if not comment_content or not comment_content.strip():
                    st.error("El comentario no puede estar vacío")
                else:
                    author_email = st.session_state.get('auth_email', '')
                    try:
                        create_comment(post_id, author_email, comment_content.strip())
                        st.success("✓ Comentario publicado")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al publicar comentario: {e}")
    else:
        st.info("Inicia sesión para comentar")


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
        st.session_state.pop('blog_content_draft', None)
        st.session_state.pop('blog_editor_mode', None)
        st.session_state.pop('markdown_images_generated', None)
        st.rerun()
    
    st.markdown(f"## {'Editar' if is_edit else 'Crear'} artículo")
    
    # Initialize session state for content draft
    current_mode = f"edit_{post_id}" if is_edit else "create"
    if st.session_state.get('blog_editor_mode') != current_mode:
        st.session_state['blog_editor_mode'] = current_mode
        st.session_state['blog_content_draft'] = post['content'] if post else ""
        st.session_state.pop('markdown_images_generated', None)
    
    # Show generated markdown BEFORE the form (if exists)
    if 'markdown_images_generated' in st.session_state and st.session_state['markdown_images_generated']:
        st.success("✅ Código Markdown generado - Copia y pega en el contenido abajo")
        st.markdown("### 📋 Código Markdown de tus imágenes")
        
        for idx, md_data in enumerate(st.session_state['markdown_images_generated']):
            col1, col2 = st.columns([1, 3])
            with col1:
                # Show preview from base64 string
                st.image(md_data['preview_base64'], width=150)
            with col2:
                st.code(md_data['markdown'], language="markdown")
        
        # All together
        st.markdown("**Todo el código junto:**")
        all_markdown = "\n\n".join([md['markdown'] for md in st.session_state['markdown_images_generated']])
        st.code(all_markdown, language="markdown")
        st.info("💡 Copia el código de arriba y pégalo en el campo 'Contenido' donde quieras las imágenes")
        st.divider()
    
    with st.form("blog_editor_form"):
        title = st.text_input(
            "Título del artículo",
            value=post['title'] if post else "",
            max_chars=200
        )
        
        ticker_input = st.text_input(
            "Ticker asociado (opcional)",
            value=post.get('ticker', '') if post else "",
            max_chars=10,
            help="Símbolo de la empresa (ej: AAPL, MSFT). Se mostrará en las búsquedas de esa empresa."
        )
        
        ticker = ticker_input.strip().upper() if ticker_input else ""
        ticker_error = None
        if ticker_input and not re.match(r'^[A-Za-z0-9]{1,10}$', ticker_input.strip()):
            ticker_error = "El ticker solo debe contener letras y números (máximo 10 caracteres)"
        
        content = st.text_area(
            "Contenido (soporta Markdown)",
            value=st.session_state.get('blog_content_draft', post['content'] if post else ''),
            height=400,
            help="Puedes usar formato Markdown: **negrita**, *cursiva*, # títulos, imágenes incrustadas, etc.",
            key="blog_content_input"
        )
        
        st.markdown("### 🖼️ Imágenes")
        st.caption("Sube imágenes y genera el código Markdown para insertarlas en el contenido")
        
        uploaded_files = st.file_uploader(
            "Subir imágenes",
            type=["png", "jpg", "jpeg", "gif"],
            accept_multiple_files=True,
            help="Selecciona imágenes para generar código Markdown",
            key="image_uploader"
        )
        
        # Image captions
        image_captions = {}
        if uploaded_files:
            st.markdown("**Descripciones de las imágenes:**")
            for idx, file in enumerate(uploaded_files):
                image_captions[file.name] = st.text_input(
                    f"Descripción para {file.name}",
                    key=f"caption_{idx}",
                    max_chars=200,
                    placeholder=file.name
                )
        
        # Two submit buttons
        col1, col2 = st.columns(2)
        with col1:
            generate_markdown = st.form_submit_button(
                "📋 Generar Código Markdown",
                use_container_width=True,
                help="Genera el código Markdown de las imágenes sin publicar"
            )
        with col2:
            submit_post = st.form_submit_button(
                "💾 " + ("Actualizar artículo" if is_edit else "Publicar artículo"),
                use_container_width=True
            )
        
        # Handle Markdown generation
        if generate_markdown:
            if uploaded_files:
                markdown_data = []
                for idx, file in enumerate(uploaded_files):
                    try:
                        img = Image.open(file)
                        img_base64 = _image_to_base64(img)
                        caption = image_captions.get(file.name, file.name)
                        markdown_line = f"![{caption}]({img_base64})"
                        
                        # Store preview as base64 string (serializable) instead of PIL Image object
                        markdown_data.append({
                            'markdown': markdown_line,
                            'preview_base64': img_base64,
                            'caption': caption
                        })
                    except Exception as e:
                        st.warning(f"Error al procesar {file.name}: {e}")
                
                if markdown_data:
                    st.session_state['markdown_images_generated'] = markdown_data
                    st.rerun()
            else:
                st.warning("Sube al menos una imagen para generar el código Markdown")
            st.stop()
        
        # Handle post submission
        if submit_post:
            # Validation
            if not title or not title.strip():
                st.error("El título es obligatorio.")
                st.stop()
            
            if not content or not content.strip():
                st.error("El contenido es obligatorio.")
                st.stop()
            
            if ticker_error:
                st.error(ticker_error)
                st.stop()
            
            # Process images for backward compatibility
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
                        images=images if images else None,
                        ticker=ticker if ticker else None
                    )
                    if success:
                        st.success("✓ Artículo actualizado correctamente")
                        st.session_state["blog_view"] = "list"
                        st.session_state.pop("editing_blog_post", None)
                        st.session_state.pop('blog_content_draft', None)
                        st.session_state.pop('blog_editor_mode', None)
                        st.session_state.pop('markdown_images_generated', None)
                        st.rerun()
                    else:
                        st.error("Error al actualizar el artículo")
                else:
                    author_email = st.session_state.get('auth_email', '')
                    new_post_id = create_blog_post(
                        title=title.strip(),
                        content=content.strip(),
                        author_email=author_email,
                        images=images,
                        ticker=ticker if ticker else None
                    )
                    st.success(f"✓ Artículo publicado correctamente (ID: {new_post_id})")
                    st.session_state["blog_view"] = "list"
                    st.session_state.pop('blog_content_draft', None)
                    st.session_state.pop('blog_editor_mode', None)
                    st.session_state.pop('markdown_images_generated', None)
                    st.rerun()
            except Exception as e:
                st.error(f"Error al guardar el artículo: {e}")


def _render_blog_list(admin: bool) -> None:
    """Render list of blog posts."""
    # Check for delete confirmation
    if "confirm_delete_post" in st.session_state:
        post_id = st.session_state["confirm_delete_post"]
        post = get_blog_post(post_id)
        
        st.warning(f"⚠️ ¿Estás seguro de que quieres eliminar el post '{post['title'] if post else 'desconocido'}'?")
        st.caption("Esta acción no se puede deshacer. También se eliminarán todos los comentarios.")
        
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("✅ Sí, eliminar", use_container_width=True):
                if delete_blog_post(post_id):
                    st.success("Post eliminado correctamente")
                    st.session_state.pop("confirm_delete_post", None)
                    st.rerun()
                else:
                    st.error("Error al eliminar el post")
        with col2:
            if st.button("❌ Cancelar", use_container_width=True):
                st.session_state.pop("confirm_delete_post", None)
                st.rerun()
        
        st.divider()
    
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
