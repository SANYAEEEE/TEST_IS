import io
import json
import os
import random
import re
import secrets
import time
import traceback
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.middleware.sessions import SessionMiddleware

import database as db

SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
QUESTIONS_PATH = Path("data/questions.json")
EXAM_QUESTION_COUNT = 25
EXAM_TIME_LIMIT = 20 * 60
MAX_AVATAR_SIZE = 2 * 1024 * 1024
AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
DEBUG = os.environ.get("DEBUG", "0") == "1"

USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_]{3,32}$")

EXAM_TOPICS = {
    "Нормативная основа и право ИБ": [
        "Нормативная основа ИБ",
        "Сертификация и лицензирование",
    ],
    "Основы ИБ и доступ": [
        "Основы ИБ, управление доступом и физическая защита",
        "Управление персоналом",
    ],
    "Сети и веб-безопасность": [
        "Сети и веб-безопасность",
        "Сетевое администрирование и облачная инфраструктура",
    ],
    "Операционные системы и терминал": [
        "Операционные системы",
        "Терминал Linux, Bash, PowerShell и CMD",
    ],
    "Технические средства и эксплуатация": [
        "Технические средства информации",
        "Эксплуатация защищённых АС",
    ],
    "Криптография и вредоносное ПО": [
        "Криптографические средства защиты",
        "Вредоносное ПО и инциденты",
    ],
    "Разработка и БД": [
        "Безопасная разработка приложений",
        "Базы данных и СУБД",
        "АИС, жизненный цикл и офисные приложения",
    ],
}

# простой rate-limit: ip -> времена запросов
_rate: dict[str, deque] = defaultdict(lambda: deque(maxlen=40))


def rate_limit(ip: str, limit: int = 10, window: int = 60) -> bool:
    """True = можно, False = слишком часто."""
    now = time.time()
    q = _rate[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


app = FastAPI(title="Подготовка к защите ИБ")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="ib_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=False,  # на Render с HTTPS можно True
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

print(f"Loading {QUESTIONS_PATH} ...", flush=True)
with open(QUESTIONS_PATH, encoding="utf-8") as f:
    ALL_QUESTIONS = json.load(f)
TOPICS = sorted({q["topic"] for q in ALL_QUESTIONS})
QUESTIONS_BY_ID = {q["id"]: q for q in ALL_QUESTIONS}
print(f"Loaded {len(ALL_QUESTIONS)} questions, {len(TOPICS)} topics", flush=True)

try:
    from grading_engine import check_answer as _check_answer
    print("grading_engine loaded", flush=True)
except Exception as e:
    _check_answer = None
    print(f"grading_engine fallback: {e}", flush=True)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    print(f">>> {request.method} {request.url.path}", flush=True)
    try:
        response = await call_next(request)
    except Exception:
        print(traceback.format_exc(), flush=True)
        if DEBUG:
            raise
        return HTMLResponse("Внутренняя ошибка сервера", status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    print(f"<<< {response.status_code} {request.method} {request.url.path}", flush=True)
    return response


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_current_user(request: Request) -> Optional[dict]:
    uid = request.session.get("user_id")
    return db.get_user_by_id(uid) if uid else None


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_hex(16)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, token: str) -> bool:
    return bool(token) and secrets.compare_digest(token, request.session.get("csrf", ""))


def build_chart(results: list) -> dict:
    chron = list(reversed(results))
    return {
        "labels": [r["created_at"][5:16] for r in chron],
        "percents": [
            round(r["score"] * 100.0 / r["max_score"], 1) if r["max_score"] else 0
            for r in chron
        ],
        "is_exam": [bool(r["is_exam"]) for r in chron],
    }


def filter_by_difficulty(pool: list, difficulty: str | None) -> list:
    if not difficulty:
        return pool
    d = difficulty.lower().replace("ё", "е")
    out = []
    for q in pool:
        qd = str(q.get("difficulty", "")).lower().replace("ё", "е")
        if qd == d:
            out.append(q)
    return out


def pick_exam_variant(pool: list, topic: str, variant: int, n: int) -> list:
    if not pool:
        return []
    n = min(n, len(pool))
    rng = random.Random(f"{topic}::{variant}")
    return rng.sample(pool, n)


def public_question(q: dict) -> dict:
    data = {
        "id": q["id"],
        "topic": q["topic"],
        "type": q["type"],
        "difficulty": q.get("difficulty"),
        "points": q.get("points", 1),
        "question": q["question"],
    }
    if q.get("scenario"):
        data["scenario"] = q["scenario"]
    if q.get("options"):
        opts = list(q["options"])
        random.shuffle(opts)
        data["options"] = opts
    if q.get("left"):
        data["left"] = q["left"]
        right = list(q.get("right", []))
        random.shuffle(right)
        data["right"] = right
    if q.get("input_hint"):
        data["input_hint"] = q["input_hint"]
    if q.get("image"):
        data["image"] = q["image"]
        data["image_alt"] = q.get("image_alt", "")
    return data


def simple_grade(q, user_answers):
    q_type, correct = q.get("type"), q.get("correct")
    try:
        if q_type in ("single", "case"):
            if isinstance(user_answers, str):
                user_answers = [user_answers] if user_answers else []
            ok = list(user_answers) == list(correct or [])
            return {"is_correct": ok, "score": 1.0 if ok else 0.0}
        if q_type == "multi":
            if not isinstance(user_answers, list):
                user_answers = [user_answers] if user_answers else []
            ok = set(user_answers) == set(correct or [])
            return {"is_correct": ok, "score": 1.0 if ok else 0.0}
        if q_type == "ordering":
            ok = list(user_answers or []) == list(correct or [])
            return {"is_correct": ok, "score": 1.0 if ok else 0.0}
        if q_type == "matching":
            ok = dict(user_answers or {}) == dict(correct or {})
            return {"is_correct": ok, "score": 1.0 if ok else 0.0}
        if q_type == "input":
            expected = correct[0] if isinstance(correct, list) and correct else str(correct or "")
            user_val = str(user_answers or "").strip().replace(",", ".")
            exp_val = str(expected).strip().replace(",", ".")
            ok = user_val == exp_val
            try:
                ok = abs(float(user_val) - float(exp_val)) < 1e-6
            except Exception:
                pass
            return {"is_correct": ok, "score": 1.0 if ok else 0.0}
    except Exception:
        pass
    return {"is_correct": False, "score": 0.0}


def grade_answer(q, user_answers):
    if _check_answer is not None:
        try:
            ok = _check_answer(q, user_answers)
            return {"is_correct": bool(ok), "score": 1.0 if ok else 0.0}
        except Exception:
            pass
    return simple_grade(q, user_answers)


async def save_avatar(file: UploadFile) -> str:
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Можно только JPG, PNG или WEBP")
    data = await file.read()
    if len(data) > MAX_AVATAR_SIZE:
        raise ValueError("Файл больше 2 МБ")
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((512, 512))
    except Exception:
        raise ValueError("Файл не является изображением")
    name = f"{uuid4().hex}.jpg"
    img.save(AVATAR_DIR / name, format="JPEG", quality=85)
    return f"/static/avatars/{name}"


@app.on_event("startup")
def startup():
    db.init_db()
    print("DB ready", flush=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("index.html", {
        "request": request, "user": user, "topics": TOPICS, "csrf": csrf_token(request),
    })


@app.get("/exam", response_class=HTMLResponse)
async def exam_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("exam.html", {
        "request": request,
        "user": user,
        "exam_topics": list(EXAM_TOPICS.keys()),
        "variants": list(range(1, 11)),
        "csrf": csrf_token(request),
    })


@app.post("/exam/start")
async def exam_start(
    request: Request,
    topic: str = Form(...),
    variant: int = Form(...),
    csrf: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not check_csrf(request, csrf):
        return HTMLResponse("Неверный CSRF-токен", status_code=400)

    bank_topics = EXAM_TOPICS.get(topic)
    if not bank_topics:
        return RedirectResponse("/exam", status_code=303)

    try:
        variant = max(1, min(int(variant), 10))
    except Exception:
        variant = 1

    pool = [q for q in ALL_QUESTIONS if q["topic"] in bank_topics]
    selected = pick_exam_variant(pool, topic, variant, EXAM_QUESTION_COUNT)
    if not selected:
        return RedirectResponse("/exam", status_code=303)

    request.session["test"] = {
        "question_ids": [q["id"] for q in selected],
        "topic_label": f"{topic} · вариант {variant}",
        "mode": "exam",
        "started_at": time.time(),
        "time_limit": EXAM_TIME_LIMIT,
    }
    return RedirectResponse("/quiz", status_code=303)


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("leaderboard.html", {
        "request": request, "user": user, "board": db.get_leaderboard(50),
    })


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request, "error": None, "csrf": csrf_token(request),
    })


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(""),
):
    if not rate_limit(client_ip(request), limit=5, window=60):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Слишком много попыток. Подождите минуту.",
            "csrf": csrf_token(request),
        })
    if not check_csrf(request, csrf):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Сессия устарела, обновите страницу.",
            "csrf": csrf_token(request),
        })

    username = username.strip()
    if not USERNAME_RE.match(username):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Логин: 3–32 символа, буквы/цифры/_",
            "csrf": csrf_token(request),
        })
    if not (4 <= len(password) <= 72):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Пароль: от 4 до 72 символов",
            "csrf": csrf_token(request),
        })
    if not db.create_user(username, password):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Такой логин уже занят",
            "csrf": csrf_token(request),
        })
    user = db.verify_user(username, password)
    request.session["user_id"] = user["id"]
    request.session["csrf"] = secrets.token_hex(16)
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request, "error": None, "csrf": csrf_token(request),
    })


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(""),
):
    if not rate_limit(client_ip(request), limit=8, window=60):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Слишком много попыток. Подождите минуту.",
            "csrf": csrf_token(request),
        })
    if not check_csrf(request, csrf):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Сессия устарела, обновите страницу.",
            "csrf": csrf_token(request),
        })

    user = db.verify_user(username.strip(), password)
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Неверный логин или пароль",
            "csrf": csrf_token(request),
        })
    request.session["user_id"] = user["id"]
    request.session["csrf"] = secrets.token_hex(16)
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    results = db.get_user_results(user["id"])
    return templates.TemplateResponse("profile.html", {
        "request": request, "user": user, "results": results,
        "chart": build_chart(results), "error": None, "ok": None,
        "csrf": csrf_token(request),
    })


@app.post("/profile")
async def profile_update(
    request: Request,
    bio: str = Form(""),
    csrf: str = Form(""),
    avatar: UploadFile = File(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not check_csrf(request, csrf):
        results = db.get_user_results(user["id"])
        return templates.TemplateResponse("profile.html", {
            "request": request, "user": user, "results": results,
            "chart": build_chart(results), "error": "Сессия устарела", "ok": None,
            "csrf": csrf_token(request),
        })

    error = ok = None
    avatar_path = None
    bio = (bio or "").strip()[:500]
    if avatar and avatar.filename:
        try:
            avatar_path = await save_avatar(avatar)
        except ValueError as e:
            error = str(e)
    if not error:
        db.update_profile(user["id"], bio=bio, avatar=avatar_path)
        ok = "Профиль обновлён"
        user = db.get_user_by_id(user["id"])
    results = db.get_user_results(user["id"])
    return templates.TemplateResponse("profile.html", {
        "request": request, "user": user, "results": results,
        "chart": build_chart(results), "error": error, "ok": ok,
        "csrf": csrf_token(request),
    })


@app.post("/start")
async def start_test(
    request: Request,
    count: int = Form(20),
    difficulty: str = Form(""),
    csrf: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not check_csrf(request, csrf):
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    general = form.get("general")
    topics = form.getlist("topics")
    difficulty = (difficulty or "").strip()

    if general or not topics:
        pool = ALL_QUESTIONS[:]
        topic_label = "Общий тест"
    else:
        pool = [q for q in ALL_QUESTIONS if q["topic"] in topics]
        topic_label = ", ".join(topics)

    pool = filter_by_difficulty(pool, difficulty or None)
    if difficulty:
        topic_label = f"{topic_label} · {difficulty}"

    if not pool:
        return RedirectResponse("/", status_code=303)

    try:
        count = max(1, min(int(count), len(pool), 100))
    except Exception:
        count = 20
    selected = random.sample(pool, count)
    request.session["test"] = {
        "question_ids": [q["id"] for q in selected],
        "topic_label": topic_label,
        "mode": "practice",
        "started_at": time.time(),
        "time_limit": None,
    }
    return RedirectResponse("/quiz", status_code=303)


@app.get("/quiz", response_class=HTMLResponse)
async def quiz_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    test = request.session.get("test")
    if not test:
        return RedirectResponse("/", status_code=303)
    questions = [
        public_question(QUESTIONS_BY_ID[qid])
        for qid in test["question_ids"] if qid in QUESTIONS_BY_ID
    ]
    return templates.TemplateResponse("quiz.html", {
        "request": request, "user": user, "questions": questions,
        "mode": test["mode"], "time_limit": test.get("time_limit"),
        "started_at": test["started_at"], "topic_label": test["topic_label"],
        "csrf": csrf_token(request),
    })


@app.post("/submit")
async def submit_test(request: Request):
    try:
        user = get_current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        test = request.session.get("test")
        if not test:
            return RedirectResponse("/", status_code=303)

        form = await request.form()
        if not check_csrf(request, form.get("csrf", "")):
            return HTMLResponse("Неверный CSRF-токен", status_code=400)

        details, total_score, max_score = [], 0.0, 0.0
        for qid in test["question_ids"]:
            q = QUESTIONS_BY_ID.get(qid)
            if not q:
                continue
            max_score += q.get("points", 1)
            q_type = q.get("type")
            if q_type in ("single", "case"):
                a = form.get(f"q{qid}")
                user_answers = [a] if a else []
            elif q_type in ("multi", "ordering"):
                user_answers = list(form.getlist(f"q{qid}"))
            elif q_type == "matching":
                user_answers = {}
                for i, left in enumerate(q.get("left", [])):
                    val = form.get(f"q{qid}_{i}")
                    if val:
                        user_answers[left] = val
            elif q_type == "input":
                user_answers = (form.get(f"q{qid}") or "").strip()[:256]
            else:
                user_answers = []

            result = grade_answer(q, user_answers)
            points = float(result.get("score", 0)) * q.get("points", 1)
            total_score += points
            details.append({
                "id": qid,
                "question": q.get("question", ""),
                "type": q_type,
                "user_answer": user_answers,
                "correct": q.get("correct"),
                "is_correct": bool(result.get("is_correct", False)),
                "points": points,
                "max_points": q.get("points", 1),
                "explanation": q.get("explanation", ""),
            })

        duration = int(time.time() - test["started_at"])
        result_id = db.save_result(
            user_id=user["id"], topic=test["topic_label"],
            score=total_score, max_score=max_score, details=details,
            duration_sec=duration, is_exam=(test["mode"] == "exam"),
        )
        request.session.pop("test", None)
        return RedirectResponse(f"/result/{result_id}", status_code=303)
    except Exception:
        print(traceback.format_exc(), flush=True)
        if DEBUG:
            return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)
        return HTMLResponse("Ошибка при сохранении теста", status_code=500)


@app.get("/result/{result_id}", response_class=HTMLResponse)
async def result_page(request: Request, result_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    result = db.get_result(result_id)
    if not result or result["user_id"] != user["id"]:
        return RedirectResponse("/", status_code=303)
    percent = round(result["score"] * 100.0 / result["max_score"], 1) if result["max_score"] else 0
    return templates.TemplateResponse("result.html", {
        "request": request, "user": user, "result": result, "percent": percent,
    })


@app.get("/submit")
async def submit_get():
    return HTMLResponse("<p><a href='/'>На главную</a></p>")