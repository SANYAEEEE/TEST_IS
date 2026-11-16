import sqlite3
import json
import bcrypt
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/app.db")


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        raw = password.encode("utf-8")[:72]
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except Exception:
        return False


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                bio TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                details TEXT,
                duration_sec INTEGER DEFAULT 0,
                is_exam INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "bio" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
        if "avatar" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
        result_cols = [r[1] for r in conn.execute("PRAGMA table_info(results)").fetchall()]
        if "duration_sec" not in result_cols:
            conn.execute("ALTER TABLE results ADD COLUMN duration_sec INTEGER DEFAULT 0")
        if "is_exam" not in result_cols:
            conn.execute("ALTER TABLE results ADD COLUMN is_exam INTEGER DEFAULT 0")
        conn.commit()


def create_user(username: str, password: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def verify_user(username: str, password: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return dict(row)
    return None


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_profile(user_id: int, bio: str = None, avatar: str = None):
    with get_conn() as conn:
        if bio is not None and avatar is not None:
            conn.execute("UPDATE users SET bio = ?, avatar = ? WHERE id = ?", (bio, avatar, user_id))
        elif bio is not None:
            conn.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user_id))
        elif avatar is not None:
            conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar, user_id))
        conn.commit()


def save_result(user_id, topic, score, max_score, details, duration_sec=0, is_exam=False) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO results
               (user_id, topic, score, max_score, details, duration_sec, is_exam, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, topic, score, max_score,
                json.dumps(details, ensure_ascii=False),
                duration_sec, int(is_exam),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_user_results(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM results WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_result(result_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["details"] = json.loads(data["details"]) if data["details"] else []
    return data


def get_leaderboard(limit: int = 50):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.avatar,
                   MAX(CASE WHEN r.max_score > 0
                            THEN ROUND(r.score * 100.0 / r.max_score, 1)
                            ELSE 0 END) AS best_percent,
                   COUNT(r.id) AS exam_count
            FROM users u
            JOIN results r ON r.user_id = u.id AND r.is_exam = 1
            GROUP BY u.id
            ORDER BY best_percent DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]