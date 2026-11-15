import sqlite3
import json
from pathlib import Path
from datetime import datetime
from passlib.context import CryptContext

DB_PATH = Path("data/app.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            score REAL NOT NULL,
            max_score REAL NOT NULL,
            details TEXT,
            duration_sec INTEGER,
            is_exam INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)
        conn.commit()

def create_user(username: str, password: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, pwd_context.hash(password), datetime.now().isoformat(timespec="seconds"))
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def verify_user(username: str, password: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row and pwd_context.verify(password, row["password_hash"]):
        return dict(row)
    return None

def get_user_by_id(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

def save_result(user_id: int, topic: str, score: float, max_score: float,
                details: list, duration_sec: int = 0, is_exam: bool = False) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO results
               (user_id, topic, score, max_score, details, duration_sec, is_exam, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, topic, score, max_score, json.dumps(details, ensure_ascii=False),
             duration_sec, int(is_exam), datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        return cur.lastrowid

def get_user_results(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM results WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
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