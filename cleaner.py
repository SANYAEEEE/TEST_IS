import json


def remove_duplicates():
    with open('data/questions.json', 'r', encoding='utf-8') as f:
        questions = json.load(f)

    unique_questions = []
    seen_texts = set()
    seen_ids = set()

    # Сначала отсортируем по ID, чтобы оставить самые первые (или самые полные) версии
    questions.sort(key=lambda x: x['id'])

    for q in questions:
        # Нормализуем текст (убираем пробелы, приводим к нижнему регистру)
        text_key = q['question'].strip().lower()

        if text_key not in seen_texts:
            seen_texts.add(text_key)
            unique_questions.append(q)
        else:
            print(f"Удален дубликат: ID {q['id']} - {q['question'][:50]}...")

    with open('data/questions.json', 'w', encoding='utf-8') as f:
        json.dump(unique_questions, f, ensure_ascii=False, indent=2)

    print(f"Готово! Осталось вопросов: {len(unique_questions)}")


if __name__ == "__main__":
    remove_duplicates()

