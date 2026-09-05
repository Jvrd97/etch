---
name: knowledge-capture
description: "Use when user expresses confusion or asks for clarification on a concept they don't understand yet. Triggers on phrases like 'I'm confused', 'wait what', 'I don't get it', 'не понял', 'в чём разница', 'что это значит', 'как это работает'. After explaining, captures the explanation to /knowledge directory for future reference."
---

# Knowledge Capture (When User is Confused)

Когда пользователь выражает непонимание — не просто объясни, а **зафиксируй объяснение** для будущих сессий.

## Trigger Detection

Pattern matches (case-insensitive):
- "I'm confused" / "I don't understand" / "I don't get it"
- "wait, what?" / "what?" / "huh?"
- "не понял" / "не понимаю" / "не догоняю"
- "в чём разница" / "what's the difference"
- "что это значит" / "what does that mean"
- "как это работает" / "how does this work"
- "почему" / "why" — если контекстуально означает непонимание

NOT triggers:
- "I disagree" — не путать с непониманием
- "tell me more" — это запрос на подробности, не на разъяснение
- Риторические "почему так?" в раздражённом тоне — это claim, не вопрос

## Process

### 1. Сначала объясни ясно

Дай чёткое, краткое объяснение в чате. Используй:
- Аналогии из знакомых пользователю доменов
- Пример если возможно
- Сравнительные таблицы для разделения концептов
- Diagrams (mermaid) если структурное

### 2. Спроси "достаточно ли?"

После объяснения — простой вопрос: "Понятно? Если нужно глубже или с другого угла — скажи."

Не уходи в длинный лекционный режим — пусть пользователь направит дальнейшее объяснение.

### 3. Зафиксируй в `/knowledge/`

Если пользователь подтвердил что понятно (или продолжил работу не возражая):

```bash
mkdir -p knowledge
```

Создай файл `knowledge/<topic-slug>.md`:

```markdown
# <Topic Title>

> Captured: <UTC date>
> Context: <одно предложение когда возникло замешательство>

## TL;DR
<2-3 предложения суть>

## Detailed Explanation
<полное объяснение из чата>

## Examples
<если давал примеры>

## Related Concepts
- <ссылки на другие knowledge/ файлы если есть>
- <внешние ссылки если уместно>

## Common Confusions
<что часто путают с этим концептом — заполни если пользователь явно путал>
```

### 4. Сообщи пользователю

Короткое: "Сохранил в `knowledge/<filename>.md` — пригодится в следующий раз когда тема всплывёт."

## When NOT to capture

- Тривиальные вопросы ("what's `git pull`?")  — не загромождай knowledge/
- Project-specific детали — лучше в ADR или PRD
- Личные предпочтения — не общее знание
- Уже есть файл на эту тему — обнови существующий, не создавай дубль

## Maintenance

Раз в спринт:
- Просмотри `knowledge/` — устаревшие концепты пометь как [DEPRECATED]
- Дубли и пересечения консолидируй
- Связанные темы кросс-линкуй

## Anti-patterns

- ❌ Long-form lecture без проверки понимания
- ❌ Капчурить каждый чих — knowledge/ не должен быть свалкой
- ❌ Капчурить project secrets / sensitive data
- ❌ Перезаписать существующий файл без сравнения
- ❌ Игнорировать non-English триггеры (пользователь может писать на русском)
