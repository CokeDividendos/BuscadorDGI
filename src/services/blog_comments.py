# src/services/blog_comments.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from src.db import get_conn, _get_cursor, _execute_query


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def create_comment(post_id: int, author_email: str, content: str) -> int:
    """Create a new comment on a blog post."""
    conn = get_conn()
    cur = _get_cursor(conn)
    
    now = _now_iso()
    
    _execute_query(cur, """
        INSERT INTO blog_comments (post_id, author_email, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (post_id, author_email, content, now, now))
    
    comment_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return comment_id


def get_comments_by_post(post_id: int) -> List[Dict[str, Any]]:
    """Get all comments for a blog post, ordered by creation date (oldest first)."""
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, """
        SELECT * FROM blog_comments
        WHERE post_id = ?
        ORDER BY created_at ASC
    """, (post_id,))
    
    rows = cur.fetchall()
    conn.close()
    
    comments = []
    for row in rows:
        comments.append({
            "id": row["id"],
            "post_id": row["post_id"],
            "author_email": row["author_email"],
            "content": row["content"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        })
    
    return comments


def delete_comment(comment_id: int) -> bool:
    """Delete a comment by ID."""
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, "DELETE FROM blog_comments WHERE id = ?", (comment_id,))
    
    success = cur.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def count_comments(post_id: int) -> int:
    """Count total comments for a blog post."""
    conn = get_conn()
    cur = _get_cursor(conn)
    
    _execute_query(cur, "SELECT COUNT(*) as count FROM blog_comments WHERE post_id = ?", (post_id,))
    count = cur.fetchone()["count"]
    
    conn.close()
    
    return count
