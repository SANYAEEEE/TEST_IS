import json
import os
import uuid
from datetime import datetime

DATA_DIR = "data"
QUESTIONS_FILE = os.path.join(DATA_DIR, "questions.json")
RESULTS_DIR = os.path.join(DATA_DIR, "results")


def load_questions():
    if not os.path.exists(QUESTIONS_FILE):
        return []
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_result(result_data: dict):
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    result_id = str(uuid.uuid4())[:8]
    result_data["id"] = result_id
    result_data["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    filepath = os.path.join(RESULTS_DIR, f"{result_id}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return result_id


def get_result(result_id: str):
    filepath = os.path.join(RESULTS_DIR, f"{result_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def get_user_results(username: str):
    if not os.path.exists(RESULTS_DIR):
        return []

    user_results = []
    for filename in os.listdir(RESULTS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(RESULTS_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    result = json.load(f)
                    if result.get("username") == username:
                        user_results.append(result)
            except Exception:
                continue

    # Сортируем по дате (новые сверху)
    user_results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return user_results