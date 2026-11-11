import json
from collections import Counter


def validate_questions(filepath='data/questions.json'):
    print(f"--- Запуск проверки файла: {filepath} ---\n")

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            questions = json.load(f)
        except json.JSONDecodeError as e:
            print(f" КРИТИЧЕСКАЯ ОШИБКА JSON: {e}")
            return

    errors = []
    warnings = []
    ids = []
    questions_text = []

    # Проблемные ID, которые мы нашли ранее
    bad_normative_ids = [2, 178, 225, 295, 300, 311, 316, 321, 325, 329]
    obvious_ids = [92, 95, 99, 103, 105, 141, 148, 153, 156, 177, 197, 205, 255, 374, 379, 382, 522, 524, 552, 553, 554,
                   575, 578, 584]

    for q in questions:
        q_id = q.get('id')
        ids.append(q_id)

        # 1. Проверка на дубликаты текста
        text_key = q.get('question', '').strip().lower()
        questions_text.append(text_key)

        # 2. Проверка структуры (зависит от типа)
        q_type = q.get('type')

        if q_type in ["single", "multi", "case"]:
            options = q.get('options', [])
            correct = q.get('correct', [])

            if not options: errors.append(f"ID {q_id}: Пустой список options")
            if not correct: errors.append(f"ID {q_id}: Пустой список correct")

            if q_type == "single" and len(correct) > 1:
                errors.append(f"ID {q_id}: Тип single, но правильных ответов больше 1")

            for c in correct:
                if c not in options:
                    errors.append(f"ID {q_id}: Правильный ответ '{c}' отсутствует в options")

        elif q_type == "matching":
            left = q.get('left', [])
            right = q.get('right', [])
            correct = q.get('correct', {})

            for l, r in correct.items():
                if l not in left: errors.append(f"ID {q_id}: В correct ключ '{l}' отсутствует в left")
                if r not in right: errors.append(f"ID {q_id}: В correct значение '{r}' отсутствует в right")

        elif q_type == "ordering":
            options = q.get('options', [])
            correct = q.get('correct', [])
            if len(options) != len(correct):
                errors.append(f"ID {q_id}: Количество вариантов не совпадает с количеством правильных ответов")
            for c in correct:
                if c not in options:
                    errors.append(f"ID {q_id}: Правильный элемент '{c}' отсутствует в options")

        # 3. Проверка на плохие пояснения
        explanation = q.get('explanation', '')
        if len(explanation) < 30:
            warnings.append(f"ID {q_id}: Слишком короткое пояснение ({len(explanation)} симв.)")

        # 4. Проверка на очевидные вопросы и нормативку
        if q_id in bad_normative_ids:
            warnings.append(f"ID {q_id}: НОРМАТИВНЫЙ ВОПРОС (требует сверки с законом)")
        if q_id in obvious_ids:
            warnings.append(f"ID {q_id}: СЛИШКОМ ОЧЕВИДНЫЙ вопрос")

    # 5. Проверка дубликатов ID
    id_counts = Counter(ids)
    for id_val, count in id_counts.items():
        if count > 1:
            errors.append(f"ID {id_val}: Встречается {count} раз!")

    # 6. Проверка дубликатов текста
    text_counts = Counter(questions_text)
    for text, count in text_counts.items():
        if count > 1:
            warnings.append(f"ДУБЛИКАТ ТЕКСТА (встречается {count} раз): '{text[:50]}...'")

    # Вывод результатов
    print(f" Всего проверено вопросов: {len(questions)}")
    print(f" Найдено ошибок (ломают тест): {len(errors)}")
    for err in errors:
        print(f"  - {err}")

    print(f"\n⚠️ Найдено предупреждений (нужно исправить): {len(warnings)}")
    for warn in warnings:
        print(f"  - {warn}")


if __name__ == "__main__":
    validate_questions()