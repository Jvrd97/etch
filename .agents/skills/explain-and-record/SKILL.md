---
name: explain-and-record
description: "Use when user explicitly asks for an explanation of a concept, technology, pattern, or how something works. Triggers on 'explain X', 'how does Y work', 'what is Z', 'tell me about', 'объясни', 'расскажи про', 'как работает', 'что такое'. Provides the explanation AND records it in /knowledge for future reference."
---

# Explain and Record

Когда пользователь явно просит объяснение — дай его, но также зафиксируй для будущих сессий, чтобы не объяснять второй раз.

## Trigger Detection

Explicit explanation requests:
- "Explain X" / "how does X work" / "what is X"
- "tell me about" / "give me an overview"
- "объясни" / "расскажи про" / "что такое"
- "как работает" / "как устроено"
- "what's the difference between X and Y"

This is **different from** `knowledge-capture` skill:
- `knowledge-capture`: triggers on **confusion** (passive, user is stuck)
- `explain-and-record`: triggers on **explicit request** (active, user is learning)

Both end up writing to `/knowledge/`, but explain-and-record can produce **longer, structured** content because user asked for it deliberately.

## Process

### 1. Гibrid response: in-chat + file

Дай объяснение в чате (с подходящей глубиной), и **параллельно** сохрани полную версию в `/knowledge/`.

В чате:
- Длина пропорциональна вопросу. "What is async?" — 3-4 параграфа. "Explain the entire async ecosystem" — может быть длиннее, но используй headers.
- Используй examples, аналогии, сравнения
- Tables для сравнительных вопросов
- Mermaid diagrams для структурных концептов

### 2. Структура knowledge файла

```markdown
# <Concept Name>

> Recorded: <UTC date>
> Triggered by: "<original question>"

## TL;DR
<one-liner — что это>

## Definition
<точное определение>

## Why it matters
<когда и зачем используется>

## How it works
<механизм — может быть с диаграммой>

## Examples
### Basic example
\`\`\`<language>
<code or text>
\`\`\`

### Real-world example
<если применимо к проекту>

## Comparison with alternatives
| | This | Alternative A | Alternative B |
|---|---|---|---|
| When to use | ... | ... | ... |
| Complexity | ... | ... | ... |
| Trade-offs | ... | ... | ... |

## Common pitfalls
- <трap 1>
- <трap 2>

## In this project
<если объяснение связано с конкретным project context — где используется в codebase>

## References
- <link to docs>
- <link to related knowledge files>
```

Не все секции обязательны — заполняй те которые имеют смысл для конкретного концепта.

### 3. После сохранения

В чате коротко: "Записал в `knowledge/<filename>.md` — теперь это в knowledge base."

### 4. Cross-linking

Перед сохранением — глянь `ls knowledge/`. Если есть связанные файлы:
- Добавь cross-link в новом файле
- Опционально обнови существующие файлы с обратной ссылкой

## Topic naming

Slug формат: `<category>-<concept>.md`

Examples:
- `python-async-await.md`
- `architecture-event-sourcing.md`
- `db-vector-similarity.md`
- `Codex-skills-vs-commands.md`

Категории помогают когда knowledge/ разрастётся.

## When NOT to record

- Quick syntax questions ("how to format date in Python") — это googleable, не нужно в проекте
- Personal opinion questions ("what do you think about X") — это не объяснение, это мнение
- Project-internal details which change ("how is our auth flow") — это в ADR/docs, не в knowledge/
- User asks "explain my code" — это code review, не general knowledge

## Anti-patterns

- ❌ Lecture-mode без структуры
- ❌ Перезаписать knowledge без diff против существующего
- ❌ Слишком общие topics (`python.md`) — конкретно (`python-typing.md`)
- ❌ Записать без cross-linking — изолированные файлы быстро устаревают
- ❌ Включать рантайм-данные (current versions, current state) — knowledge должно быть concept-level

## Output examples

User: "Объясни, что такое vertical slice"

→ В чате: 4-параграфное объяснение с горизонтальным vs вертикальным примером
→ Сохранил: `knowledge/architecture-vertical-slices.md`
→ Cross-linked: `knowledge/architecture-tracer-bullets.md` (если уже был)
→ Ответ: "Записал в knowledge/architecture-vertical-slices.md."

User: "What's the difference between skill and command in Codex?"

→ В чате: сравнительная таблица + примеры из их пака
→ Сохранил: `knowledge/Codex-skills-vs-commands.md`
→ Cross-linked: создаст или обновит `knowledge/Codex-agents.md`
→ Ответ: "Записал в knowledge/Codex-skills-vs-commands.md."
