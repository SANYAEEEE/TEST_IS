import sqlite3
import json
import os
from datetime import datetime
from passlib.context import CryptContext
from typing import Optional

DB_PATH = "data/app.db"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Создаёт таблицы, если их ещё нет"""
    os.makedirs("data", exist_ok=True)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            avatar TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            score REAL NOT NULL,
            max_score REAL NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

# ========== Пользователи ==========

def create_user(username: str, password: str) -> Optional[int]:
    """Создаёт пользователя. Возвращает id или None, если ник занят"""
    password_hash = pwd_context.hash(password)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        return None

def verify_user(username: str, password: str) -> Optional[dict]:
    """Проверяет логин и пароль. Возвращает пользователя или None"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and pwd_context.verify(password, user["password_hash"]):
        return dict(user)
    return None

def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_username(username: str) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

# ========== Результаты ==========

def save_result(user_id: int, topic: str, score: float, max_score: float, details: list) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO results (user_id, topic, score, max_score, details)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, topic, score, max_score, json.dumps(details, ensure_ascii=False))
    )
    conn.commit()
    result_id = cursor.lastrowid
    conn.close()
    return result_id

def get_user_results(user_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM results 
           WHERE user_id = ? 
           ORDER BY created_at DESC""",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_result_by_id(result_id: int) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM results WHERE id = ?", (result_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["details"] = json.loads(result["details"]) if result["details"] else []
        return result
    return None