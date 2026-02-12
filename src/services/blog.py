# src/services/blog.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.db import get_conn, _get_cursor, _execute_query


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def create_blog_post(
    title: str,
    content: str,
    author_email: str,
    images: Optional[List[Dict[str, Any]]] = None,
    ticker: Optional[str] = None
) -> int:
    """
    Create a new blog post.
    
    Args:
        title: Post title
        content: Post content (can be markdown)
        author_email: Email of the author
        images: List of image data dictionaries (optional)
        ticker: Stock ticker symbol (optional)
    
    Returns:
        The ID of the created post
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    now = _now_iso()
    images_json = json.dumps(images or [])
    
    # Normalize ticker to uppercase and strip whitespace
    ticker_normalized = ticker.strip().upper() if ticker else None
    
    _execute_query(cur, """
        INSERT INTO blog_posts (title, content, author_email, published_date, created_at, updated_at, images_json, ticker)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, content, author_email, now, now, now, images_json, ticker_normalized))
    
    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return post_id


def get_blog_post(post_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a blog post by ID.
    
    Args:
        post_id: The post ID
    
    Returns:
        Post data as a dictionary, or None if not found
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, "SELECT * FROM blog_posts WHERE id = ?", (post_id,))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "author_email": row["author_email"],
        "published_date": row["published_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "ticker": row["ticker"] if "ticker" in row.keys() else None,
        "images": json.loads(row["images_json"]) if row["images_json"] else []
    }


def list_blog_posts(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    List all blog posts, ordered by published date (newest first).
    
    Args:
        limit: Maximum number of posts to return
        offset: Number of posts to skip
    
    Returns:
        List of post dictionaries
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, """
        SELECT * FROM blog_posts
        ORDER BY published_date DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    
    rows = cur.fetchall()
    conn.close()
    
    posts = []
    for row in rows:
        posts.append({
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "author_email": row["author_email"],
            "published_date": row["published_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "ticker": row["ticker"] if "ticker" in row.keys() else None,
            "images": json.loads(row["images_json"]) if row["images_json"] else []
        })
    
    return posts


def update_blog_post(
    post_id: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
    images: Optional[List[Dict[str, Any]]] = None,
    ticker: Optional[str] = None
) -> bool:
    """
    Update an existing blog post.
    
    Args:
        post_id: The post ID to update
        title: New title (optional)
        content: New content (optional)
        images: New images list (optional)
        ticker: Stock ticker symbol (optional)
    
    Returns:
        True if the update was successful, False otherwise
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    # Normalize ticker to uppercase and strip whitespace
    ticker_normalized = ticker.strip().upper() if ticker else None
    
    # Build update query safely using predefined column mappings
    allowed_updates = {
        'title': title,
        'content': content,
        'images_json': json.dumps(images) if images is not None else None,
        'ticker': ticker_normalized
    }
    
    # Filter out None values
    update_fields = {k: v for k, v in allowed_updates.items() if v is not None}
    
    if not update_fields:
        conn.close()
        return False
    
    # Build the SET clause safely
    set_clauses = [f"{col} = ?" for col in update_fields.keys()]
    params = list(update_fields.values())
    
    # Always update the updated_at timestamp
    set_clauses.append("updated_at = ?")
    params.append(_now_iso())
    
    # Add post_id to params
    params.append(post_id)
    
    query = f"UPDATE blog_posts SET {', '.join(set_clauses)} WHERE id = ?"
    _execute_query(cur, query, tuple(params))
    
    success = cur.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def delete_blog_post(post_id: int) -> bool:
    """
    Delete a blog post by ID.
    
    Args:
        post_id: The post ID to delete
    
    Returns:
        True if the post was deleted, False otherwise
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, "DELETE FROM blog_posts WHERE id = ?", (post_id,))
    
    success = cur.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def count_blog_posts() -> int:
    """
    Count the total number of blog posts.
    
    Returns:
        Total number of posts
    """
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, "SELECT COUNT(*) as count FROM blog_posts", ())
    count = cur.fetchone()["count"]
    conn.close()
    
    return count


def get_blog_posts_by_ticker(ticker: str) -> List[Dict[str, Any]]:
    """Get all blog posts associated with a ticker symbol."""
    conn = get_conn()
    cur = _get_cursor(conn)
    
    # Normalize ticker to uppercase
    ticker_normalized = ticker.strip().upper()
    
    _execute_query(cur, """
        SELECT * FROM blog_posts 
        WHERE ticker = ? 
        ORDER BY published_date DESC
    """, (ticker_normalized,))
    
    rows = cur.fetchall()
    conn.close()
    
    posts = []
    for row in rows:
        posts.append({
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "author_email": row["author_email"],
            "published_date": row["published_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "ticker": row["ticker"] if "ticker" in row.keys() else None,
            "images": json.loads(row["images_json"]) if row["images_json"] else []
        })
    
    return posts
