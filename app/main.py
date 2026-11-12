import random
from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import app.database as database

app = FastAPI(title="ИБ Тест")
app.add_middleware(SessionMiddleware, secret_key="super-secret-key-change-me-in-production-2026")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Инициализация базы при запуске
database.init_db()

TOPICS = [
    "Нормативная основа ИБ", "Основы ИБ", "Сети",
    "Операционные системы", "Управление персоналом",
    "Вредоносное ПО и инциденты", "Сертификация и лицензирование"
]

def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        return database.get_user_by_id(user_id)
    return None

# ========== Главная ==========

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "topics": TOPICS
    })

# ========== Регистрация ==========

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    if len(username.strip()) < 3:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Ник должен быть не короче 3 символов"
        })
    if len(password) < 4:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Пароль должен быть не короче 4 символов"
        })
    if password != password2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Пароли не совпадают"
        })

    user_id = database.create_user(username, password)
    if not user_id:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Такой ник уже занят"
        })

    request.session["user_id"] = user_id
    return RedirectResponse("/", status_code=303)

# ========== Вход ==========

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = database.verify_user(username, password)
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверный ник или пароль"
        })

    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)

# ========== Выход ==========

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

# ========== Старт теста ==========

@app.post("/start")
async def start_test(
    request: Request,
    topics: list[str] = Form(default=[]),
    marathon: str = Form(None)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Здесь пока оставляем старую логику загрузки вопросов из JSON
    # (позже перенесём и вопросы в БД)
    import json
    with open("data/questions.json", "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    if "general" in topics or not topics:
        pool = all_questions.copy()
        display_topic = "Общий тест"
        target_count = 30
    else:
        pool = [q for q in all_questions if q["topic"] in topics]
        display_topic = ", ".join(topics)
        target_count = 21

    is_marathon = (marathon == "true")
    if is_marathon:
        target_count = 40

    random.shuffle(pool)
    selected = pool[:target_count]

    for q in selected:
        if q.get("type") in ["single", "multi", "case"] and "options" in q:
            random.shuffle(q["options"])

    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "user": user,
        "username": user["username"],
        "topic": display_topic,
        "questions": selected,
        "is_marathon": is_marathon
    })

# ========== Отправка теста ==========

@app.post("/submit")
async def submit_test(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    form_data = await request.form()
    topic = form_data.get("topic", "Общий тест")

    import json
    with open("data/questions.json", "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    questions_map = {str(q["id"]): q for q in all_questions}
    score = 0
    max_score = 0
    details = []

    question_ids = form_data.getlist("question_ids")

    for q_id in question_ids:
        q = questions_map.get(q_id)
        if not q:
            continue

        max_score += q.get("points", 1)
        user_answer = form_data.getlist(f"q_{q_id}")
        correct = set(q.get("correct", []))
        chosen = set(user_answer)

        is_correct = chosen == correct
        earned = q.get("points", 1) if is_correct else 0
        score += earned

        details.append({
            "question": q,
            "user_answer": user_answer,
            "is_correct": is_correct,
            "earned": earned
        })

    result_id = database.save_result(
        user_id=user["id"],
        topic=topic,
        score=score,
        max_score=max_score,
        details=details
    )

    return RedirectResponse(f"/result/{result_id}", status_code=303)

# ========== Результат ==========

@app.get("/result/{result_id}", response_class=HTMLResponse)
async def result_page(request: Request, result_id: int):
    user = get_current_user(request)
    result = database.get_result_by_id(result_id)
    if not result:
        return HTMLResponse("Результат не найден", status_code=404)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "user": user,
        "result": result
    })

# ========== Профиль ==========

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    results = database.get_user_results(user["id"])
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "results": results
    })