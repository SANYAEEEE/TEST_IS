import random
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import app.database as database
import json

app = FastAPI(title="ИБ Тест")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

TOPICS = [
    "Нормативная основа ИБ", "Основы ИБ", "Сети",
    "Операционные системы", "Управление персоналом",
    "Вредоносное ПО и инциденты", "Сертификация и лицензирование"
]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"topics": TOPICS})


@app.post("/start")
async def start_test(request: Request, username: str = Form(...), topics: list[str] = Form(default=[]), marathon: str = Form(None)):
    # Вот эта строчка была потеряна, она загружает вопросы
    all_questions = database.load_questions()

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
    else:
        easy, medium, hard = [], [], []
        for q in pool:
            diff = str(q.get("difficulty", "")).strip().lower()
            if "лёг" in diff or "лег" in diff: easy.append(q)
            elif "сред" in diff: medium.append(q)
            elif "слож" in diff: hard.append(q)
            else: medium.append(q)

        random.shuffle(easy)
        random.shuffle(medium)
        random.shuffle(hard)

        selected = []
        per_bucket = target_count // 3
        remainder = target_count % 3

        take = per_bucket + (1 if remainder > 0 else 0)
        selected.extend(easy[:take])
        remainder -= (1 if remainder > 0 else 0)

        take = per_bucket + (1 if remainder > 0 else 0)
        selected.extend(medium[:take])
        remainder -= (1 if remainder > 0 else 0)

        take = per_bucket + (1 if remainder > 0 else 0)
        selected.extend(hard[:take])

        if len(selected) < target_count:
            remaining = easy[take:] + medium[take:] + hard[take:]
            random.shuffle(remaining)
            selected.extend(remaining[:target_count - len(selected)])

        def difficulty_order(q):
            diff = str(q.get("difficulty", "")).strip().lower()
            if "лёг" in diff or "лег" in diff: return 1
            if "сред" in diff: return 2
            if "слож" in diff: return 3
            return 4

        selected.sort(key=difficulty_order)

    for q in selected:
        if q["type"] in ["single", "multi", "case"]:
            random.shuffle(q["options"])
        elif q["type"] == "matching":
            random.shuffle(q["right"])

    return templates.TemplateResponse(request=request, name="quiz.html", context={
        "username": username,
        "topic": display_topic,
        "questions": selected,
        "is_marathon": is_marathon
    })


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, username: str = ""):
    # Если имя не передано, показываем страницу с формой поиска
    if not username:
        return templates.TemplateResponse(request=request, name="profile_search.html")

    results = database.get_user_results(username)
    return templates.TemplateResponse(request=request, name="profile.html", context={
        "username": username,
        "results": results
    })




@app.post("/submit", response_class=HTMLResponse)
async def submit_test(request: Request):
    form_data = await request.form()
    username = form_data.get("username")
    topic = form_data.get("topic")

    all_questions = database.load_questions()
    score = 0
    max_score = 0
    details = []

    question_ids = form_data.getlist("question_ids")
    questions_map = {str(q["id"]): q for q in all_questions}

    for q_id in question_ids:
        q = questions_map[q_id]
        max_score += q["points"]
        user_answer = None
        is_correct = False
        earned_points = 0
        user_matches = {}
        user_order = []

        if q["type"] in ["single", "multi", "case"]:
            user_answer = form_data.getlist(f"q_{q_id}")
            correct = set(q["correct"])
            chosen = set(user_answer)

            if q["type"] == "single":
                is_correct = chosen == correct
                earned_points = q["points"] if is_correct else 0
            else:
                correct_chosen = len(correct.intersection(chosen))
                incorrect_chosen = len(chosen - correct)
                if correct_chosen > 0:
                    ratio = (correct_chosen - incorrect_chosen) / len(correct)
                    earned_points = max(0, round(ratio * q["points"], 2))
                is_correct = chosen == correct

        elif q["type"] == "ordering":
            for i in range(len(q["options"])):
                val = form_data.get(f"q_{q_id}_order_{i}")
                if val:
                    user_order.append(q["options"][int(val) - 1])
            is_correct = user_order == q["correct"]
            earned_points = q["points"] if is_correct else 0

        elif q["type"] == "matching":
            for left_item in q["left"]:
                user_matches[left_item] = form_data.get(f"q_{q_id}_match_{left_item}")
            is_correct = user_matches == q["correct"]
            earned_points = q["points"] if is_correct else 0

        score += earned_points
        details.append({
            "question": q,
            "user_answer": user_answer if q["type"] in ["single", "multi", "case"] else (
                user_matches if q["type"] == "matching" else user_order),
            "is_correct": is_correct,
            "earned": earned_points
        })

    display_topic = "Общий тест" if topic == "general" else topic
    result_data = {
        "username": username,
        "topic": display_topic,
        "score": round(score, 2),
        "max_score": max_score,
        "details": details
    }
    result_id = database.save_result(result_data)
    return RedirectResponse(url=f"/result/{result_id}", status_code=303)

@app.get("/result/{result_id}", response_class=HTMLResponse)
async def get_result_page(request: Request, result_id: str):
    result = database.get_result(result_id)
    if not result:
        return HTMLResponse("Результат не найден", status_code=404)
    return templates.TemplateResponse(request=request, name="result.html", context={"result": result})


@app.get("/add_question", response_class=HTMLResponse)
async def add_question_page(request: Request):
    return templates.TemplateResponse(request=request, name="add_question.html")


@app.post("/add_question")
async def add_question(
        topic: str = Form(...),
        difficulty: str = Form(...),
        question: str = Form(...),
        opt1: str = Form(...),
        opt2: str = Form(...),
        opt3: str = Form(...),
        opt4: str = Form(...),
        correct: str = Form(...),
        explanation: str = Form(...)
):
    all_questions = database.load_questions()

    # ПРОВЕРКА: нет ли уже такого вопроса? (сравниваем текст без учета регистра)
    for q in all_questions:
        if q["question"].strip().lower() == question.strip().lower():
            # Если нашли такой же — возвращаем ошибку
            return HTMLResponse(
                f"<h1>Ошибка!</h1><p>Вопрос с таким текстом уже есть в базе (ID {q['id']}).</p><a href='/add_question'>Назад</a>",
                status_code=400)

    # Вычисляем новый ID
    new_id = max([q["id"] for q in all_questions]) + 1 if all_questions else 1

    points = 1
    if difficulty == "Средний":
        points = 2
    elif difficulty == "Сложный":
        points = 3

    new_q = {
        "id": new_id,
        "topic": topic,
        "type": "single",
        "difficulty": difficulty,
        "points": points,
        "question": question,
        "options": [opt1, opt2, opt3, opt4],
        "correct": [correct],
        "explanation": explanation
    }

    all_questions.append(new_q)

    # Сохраняем
    with open('data/questions.json', 'w', encoding='utf-8') as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)

    return RedirectResponse(url="/add_question", status_code=303)