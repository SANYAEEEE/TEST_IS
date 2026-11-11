import json

with open('data/questions.json', 'r', encoding='utf-8') as f:
    questions = json.load(f)

for q in questions:
    # Для ID 92 правильный ответ теперь "Оба варианта (выезд и частная жизнь)"
    if q['id'] == 92:
        q['correct'] = ["Оба варианта (выезд и частная жизнь)"]

    # Для ID 103 правильный ответ теперь "Оба варианта (обязательство и инструктаж)"
    if q['id'] == 103:
        q['correct'] = ["Оба варианта (обязательство и инструктаж)"]

with open('data/questions.json', 'w', encoding='utf-8') as f:
    json.dump(questions, f, ensure_ascii=False, indent=2)

print("Готово! Ошибки в ID 92 и 103 исправлены.")