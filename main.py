import json
import random
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import database as db

# ===================== НАСТРОЙКИ =====================
SECRET_KEY = "change-this-to-a-long-random-string"
QUESTIONS_PATH = Path("data/questions.json")
EXAM_TIME_LIMIT = 20 * 60  # 20 минут

app = FastAPI(title="Подготовка к защите ИБ")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ===================== ЛОГИ =====================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f">>> {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        print(f"<<< {response.status_code} {request.method} {request.url.path}")
        return response
    except Exception:
        print("!!! UNHANDLED EXCEPTION")
        print(traceback.format_exc())
        raise


# ===================== БАНК =====================
print(f"Loading questions from {QUESTIONS_PATH} ...")
with open(QUESTIONS_PATH, encoding="utf-8") as f:
    ALL_QUESTIONS = json.load(f)

TOPICS = sorted({q["topic"] for q in ALL_QUESTIONS})
QUESTIONS_BY_ID = {q["id"]: q for q in ALL_QUESTIONS}
print(f"Loaded {len(ALL_QUESTIONS)} questions, {len(TOPICS)} topics")


# ===================== ХЕЛПЕРЫ =====================
def get_current_user(request: Request) -> Optional[dict]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


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


def simple_grade(q: dict, user_answers) -> dict:
    q_type = q.get("type")
    correct = q.get("correct")

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
    except Exception as e:
        print(f"simple_grade error for q{q.get('id')}: {e}")

    return {"is_correct": False, "score": 0.0}


# grading_engine (если есть)
try:
    from grading_engine import check_answer as _check_answer
    print("grading_engine.check_answer loaded")
except Exception as e:
    _check_answer = None
    print(f"grading_engine not loaded, using simple_grade ({e})")


def grade_answer(q: dict, user_answers) -> dict:
    if _check_answer is not None:
        try:
            ok = _check_answer(q, user_answers)
            return {"is_correct": bool(ok), "score": 1.0 if ok else 0.0}
        except Exception as e:
            print(f"check_answer failed for q{q.get('id')}: {e}")
    return simple_grade(q, user_answers)


# ===================== STARTUP =====================
@app.on_event("startup")
def startup():
    print("Init DB...")
    db.init_db()
    print("DB ready")


# ===================== ROUTES =====================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    print(f"INDEX user={user['username'] if user else None}")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "topics": TOPICS,
    })


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    print(f"REGISTER attempt: {username}")
    if len(username) < 3 or len(password) < 4:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Логин от 3 символов, пароль от 4"
        })
    if not db.create_user(username, password):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Такой логин уже занят"
        })
    user = db.verify_user(username, password)
    request.session["user_id"] = user["id"]
    print(f"REGISTER ok: {username} id={user['id']}")
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    print(f"LOGIN attempt: {username}")
    user = db.verify_user(username.strip(), password)
    if not user:
        print("LOGIN failed")
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверный логин или пароль"
        })
    request.session["user_id"] = user["id"]
    print(f"LOGIN ok: {username}")
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    print("LOGOUT")
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    results = db.get_user_results(user["id"])
    print(f"PROFILE {user['username']} results={len(results)}")
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "results": results,
    })


@app.post("/start")
async def start_test(
    request: Request,
    mode: str = Form("practice"),
    general: Optional[str] = Form(None),
    count: int = Form(20),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    topics = form.getlist("topics")

    if general or not topics:
        pool = ALL_QUESTIONS[:]
        topic_label = "Общий тест"
    else:
        pool = [q for q in ALL_QUESTIONS if q["topic"] in topics]
        topic_label = ", ".join(topics)

    if not pool:
        print("START empty pool")
        return RedirectResponse("/", status_code=303)

    count = max(1, min(int(count), len(pool), 100))
    selected = random.sample(pool, count)

    request.session["test"] = {
        "question_ids": [q["id"] for q in selected],
        "topic_label": topic_label,
        "mode": mode,
        "started_at": time.time(),
        "time_limit": EXAM_TIME_LIMIT if mode == "exam" else None,
    }
    print(f"START test user={user['username']} mode={mode} questions={count} topic={topic_label}")
    return RedirectResponse("/quiz", status_code=303)


@app.get("/quiz", response_class=HTMLResponse)
async def quiz_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    test = request.session.get("test")
    if not test:
        print("QUIZ no active test")
        return RedirectResponse("/", status_code=303)

    questions = []
    for qid in test["question_ids"]:
        q = QUESTIONS_BY_ID.get(qid)
        if q:
            questions.append(public_question(q))

    print(f"QUIZ show {len(questions)} questions")
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "user": user,
        "questions": questions,
        "mode": test["mode"],
        "time_limit": test.get("time_limit"),
        "started_at": test["started_at"],
        "topic_label": test["topic_label"],
    })


@app.post("/submit")
async def submit_test(request: Request):
    print("=== SUBMIT START ===")
    try:
        user = get_current_user(request)
        if not user:
            print("SUBMIT no user")
            return RedirectResponse("/login", status_code=303)

        test = request.session.get("test")
        if not test:
            print("SUBMIT no test in session")
            return RedirectResponse("/", status_code=303)

        form = await request.form()
        print(f"SUBMIT form keys sample: {list(form.keys())[:10]}")

        details = []
        total_score = 0.0
        max_score = 0.0

        for qid in test["question_ids"]:
            q = QUESTIONS_BY_ID.get(qid)
            if not q:
                print(f"SUBMIT missing question id={qid}")
                continue

            max_score += q.get("points", 1)
            q_type = q.get("type")

            if q_type in ("single", "case"):
                user_answer = form.get(f"q{qid}")
                user_answers = [user_answer] if user_answer else []
            elif q_type == "multi":
                user_answers = list(form.getlist(f"q{qid}"))
            elif q_type == "ordering":
                user_answers = list(form.getlist(f"q{qid}"))
            elif q_type == "matching":
                user_answers = {}
                for i, left in enumerate(q.get("left", [])):
                    val = form.get(f"q{qid}_{i}")
                    if val:
                        user_answers[left] = val
            elif q_type == "input":
                user_answers = (form.get(f"q{qid}") or "").strip()
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
        print(f"SUBMIT score={total_score}/{max_score} duration={duration}s details={len(details)}")

        result_id = db.save_result(
            user_id=user["id"],
            topic=test["topic_label"],
            score=total_score,
            max_score=max_score,
            details=details,
            duration_sec=duration,
            is_exam=(test["mode"] == "exam"),
        )
        print(f"SUBMIT saved result_id={result_id}")

        request.session.pop("test", None)
        return RedirectResponse(f"/result/{result_id}", status_code=303)

    except Exception:
        tb = traceback.format_exc()
        print("SUBMIT ERROR:")
        print(tb)
        return HTMLResponse(
            f"<h2>Ошибка при сохранении теста</h2><pre>{tb}</pre>",
            status_code=500,
        )


@app.get("/result/{result_id}", response_class=HTMLResponse)
async def result_page(request: Request, result_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    result = db.get_result(result_id)
    if not result or result["user_id"] != user["id"]:
        print(f"RESULT forbidden or missing id={result_id}")
        return RedirectResponse("/", status_code=303)

    print(f"RESULT show id={result_id} score={result['score']}/{result['max_score']}")
    return templates.TemplateResponse("result.html", {
        "request": request,
        "user": user,
        "result": result,
    })