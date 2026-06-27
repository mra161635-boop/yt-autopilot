"""
utils/db.py — SQLite persistence layer.
Stores ideas, published videos, performance stats, and the channel strategy memo.
"""

import sqlite3, json, os
from datetime import datetime
from config import DB_PATH


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS ideas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            hook        TEXT,
            keywords    TEXT,
            score       REAL DEFAULT 0,
            status      TEXT DEFAULT 'pending',   -- pending | scripted | produced | published | skipped
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS videos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id         INTEGER REFERENCES ideas(id),
            youtube_id      TEXT,
            title           TEXT,
            description     TEXT,
            tags            TEXT,
            script_path     TEXT,
            video_path      TEXT,
            thumbnail_path  TEXT,
            published_at    TEXT,
            views           INTEGER DEFAULT 0,
            likes           INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            avg_watch_pct   REAL DEFAULT 0,
            last_checked    TEXT
        );

        CREATE TABLE IF NOT EXISTS strategy (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            memo        TEXT,
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        INSERT OR IGNORE INTO strategy (id, memo) VALUES (1,
            'No data yet. Generate initial ideas based on channel niche.');
        """)
    print("[DB] Initialised.")


# ── Ideas ──────────────────────────────────────────────────────────────────────

def save_ideas(ideas: list[dict]):
    """Insert new ideas (skips duplicates by title)."""
    with get_conn() as c:
        for idea in ideas:
            existing = c.execute("SELECT id FROM ideas WHERE title = ?", (idea["title"],)).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO ideas (title, hook, keywords, score) VALUES (?,?,?,?)",
                    (idea["title"], idea.get("hook",""), json.dumps(idea.get("keywords",[])), idea.get("score",0))
                )


def get_next_idea() -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM ideas WHERE status = 'pending' ORDER BY score DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def update_idea_status(idea_id: int, status: str):
    with get_conn() as c:
        c.execute("UPDATE ideas SET status = ? WHERE id = ?", (status, idea_id))


def pending_idea_count() -> int:
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM ideas WHERE status='pending'").fetchone()[0]


# ── Videos ────────────────────────────────────────────────────────────────────

def save_video(data: dict) -> int:
    with get_conn() as c:
        cur = c.execute("""
            INSERT INTO videos (idea_id, title, description, tags, script_path, video_path, thumbnail_path)
            VALUES (:idea_id, :title, :description, :tags, :script_path, :video_path, :thumbnail_path)
        """, data)
        return cur.lastrowid


def mark_published(video_id: int, youtube_id: str):
    with get_conn() as c:
        c.execute(
            "UPDATE videos SET youtube_id=?, published_at=? WHERE id=?",
            (youtube_id, datetime.utcnow().isoformat(), video_id)
        )


def get_published_videos() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM videos WHERE youtube_id IS NOT NULL ORDER BY published_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_video_stats(youtube_id: str, views: int, likes: int, comments: int, avg_watch_pct: float):
    with get_conn() as c:
        c.execute("""
            UPDATE videos
            SET views=?, likes=?, comments=?, avg_watch_pct=?, last_checked=?
            WHERE youtube_id=?
        """, (views, likes, comments, avg_watch_pct, datetime.utcnow().isoformat(), youtube_id))


# ── Strategy Memo ─────────────────────────────────────────────────────────────

def get_strategy() -> str:
    with get_conn() as c:
        return c.execute("SELECT memo FROM strategy WHERE id=1").fetchone()["memo"]


def save_strategy(memo: str):
    with get_conn() as c:
        c.execute(
            "UPDATE strategy SET memo=?, updated_at=? WHERE id=1",
            (memo, datetime.utcnow().isoformat())
        )
