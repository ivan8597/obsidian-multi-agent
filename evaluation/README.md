# Evaluation

Каталог содержит небольшой воспроизводимый evaluation harness для retrieval, качества ссылок, keyword relevance и маршрутизации агентов.

`dataset.json` — это шаблон датасета, который следует адаптировать под конкретный Obsidian vault. Не используйте демонстрационные значения как доказательство качества системы.

## Формат предсказаний

```json
[
  {
    "retrieved_sources": ["notes/rag.md", "notes/other.md"],
    "k": 5,
    "answer": "... [OBSIDIAN-1] ...",
    "valid_citations": ["[OBSIDIAN-1]"],
    "predicted_route": "obsidian"
  }
]
```

## Запуск

```bash
python -m evaluation.evaluate --predictions evaluation/predictions.example.json
```

Скрипт выводит:

| Метрика | Значение |
|---|---|
| Recall@k | Доля вопросов, для которых ожидаемый источник попал в top-k |
| Precision@k | Простейшая precision-оценка ожидаемого источника в top-k |
| MRR | Средняя обратная позиция ожидаемого источника |
| Citation correctness | Доля ссылок в ответе, существующих среди valid citations |
| Keyword relevance | Доля ожидаемых ключевых слов, встречающихся в ответе |
| Routing accuracy | Доля правильных решений `obsidian`, `web` или `both` |

Для полноценной оценки faithfulness и context relevance следует добавить независимого judge, ручную разметку или специализированный evaluation framework. Текущие метрики намеренно детерминированы и не требуют вызова LLM.
