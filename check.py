import json

with open('data/questions.json', 'r', encoding='utf-8') as f:
    questions = json.load(f)

# Проверяем, обновились ли пояснения
updated_explanations = [1, 3, 4, 5, 8, 11, 15, 22, 48, 64]
# Проверяем, обновились ли варианты (стали менее очевидными)
updated_options = [92, 148, 153, 156, 177, 552, 553, 578]

print("=== ПРОВЕРКА ПОЯСНЕНИЙ ===")
for q in questions:
    if q['id'] in updated_explanations:
        print(f"ID {q['id']}: {q['explanation'][:80]}...") # Выводим первые 80 символов

print("\n=== ПРОВЕРКА ВАРИАНТОВ (стало ли менее очевидно) ===")
for q in questions:
    if q['id'] in updated_options:
        print(f"ID {q['id']}: {q['options']}")