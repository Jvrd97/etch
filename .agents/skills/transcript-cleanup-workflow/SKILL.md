---
name: transcript-cleanup-workflow
description: "Detects when user pastes or references raw voice transcription. Suggests /cleanup before /triage. Triggers on: stream-of-consciousness text with STT-like artifacts (missing punctuation, run-on sentences, transcription errors, fragmented phrases), files in brain-dumps/raw/, mentions of voice notes or dictation."
---

# Transcript Cleanup Workflow

Когда пользователь работает с voice transcriptions, есть отдельный шаг между записью и triage — cleanup.

## When to suggest /cleanup

Активный сигналы что текст — это raw voice transcript:

1. **Структурные**:
   - Текст идёт сплошным потоком без точек/абзацев
   - Run-on sentences длиной 3-4 строки
   - Отсутствие capitalization где должна быть
   - Фразы обрываются на середине ("и тут можно...")
   - File path содержит `raw/` или `transcript/`

2. **Лексические**:
   - Filler words: "ну", "вот", "то есть", "блять", "короче" в высокой плотности
   - Mixed terminology: "коннектор", "Connector", "connector" в одном тексте
   - Слова которые выглядят как STT ошибки: "прининятся", "айшка", "клик-сервис"
   - Двойные/тройные повторы одного слова

3. **Семантические**:
   - Резкие переключения темы без markdown структуры
   - Self-corrections ("вот это, нет, скорее вот так")
   - Hedges и uncertainty маркеры повсюду
   - Tangenты не отделённые визуально

Если ≥2 категорий присутствуют — это transcript, нужен cleanup.

## When NOT to suggest /cleanup

- Текст явно написанный (хорошая пунктуация, абзацы, форматирование)
- Короткий direct запрос ("сделай X")
- Code snippets
- Файл уже в `brain-dumps/` (не `raw/`) — вероятно уже почищен
- Markdown-структурированный текст с заголовками

## How to suggest

Когда видишь raw transcript characteristics:

```
Этот текст похож на raw voice transcript (без пунктуации, mixed terminology,
fragmented phrases). Рекомендую сначала почистить:

  /cleanup <path или paste>

Потом /triage уже на чистом тексте — разбор будет точнее.

Продолжить с raw версией или сначала /cleanup?
```

Дай пользователю выбор — иногда он осознанно хочет работать с raw.

## Pipeline position

```mermaid
flowchart LR
    Voice[Голос/дикование] --> STT[STT/Whisper/etc]
    STT --> RawFile[brain-dumps/raw/]
    RawFile --> Cleanup[/cleanup]
    Cleanup --> CleanFile[brain-dumps/]
    CleanFile --> Triage[/triage]
    Triage --> TriagedFile[brain-dumps/triaged/]
    TriagedFile --> Grill[/grill-me or /grill-me-arch]
```

Cleanup — между записью и triage. Не пропускать.

## Folder convention

Установленная структура:

```
brain-dumps/
├── raw/                                # Raw transcripts (preserve as evidence)
│   ├── 2026-05-09-connector.md
│   └── 2026-05-12-architecture.md
├── 2026-05-09-connector.md             # Cleaned version (output of /cleanup)
├── 2026-05-12-architecture.md
├── triaged/                            # Triage reports
│   ├── 2026-05-09-connector-triage.md
│   └── 2026-05-12-architecture-triage.md
└── processed/                          # Old dumps (done with)
```

Cleanup читает из `raw/`, пишет в `brain-dumps/` (parent). Original в `raw/` остаётся для reference.

## Connection to other tools

- **Before**: STT tools (Whisper, MacWhisper, Aiko, etc.) → produces raw text
- **After**: `/triage` consumes cleaned text → produces concerns
- **Sibling**: `/explain-and-record` — different purpose (explain a concept), не для cleanup
- **Not**: `/grill-me` напрямую — грилинг не для парсинга raw текста

## Quality bar

После `/cleanup` текст должен быть:
- Читаемым (можешь дать другому человеку — поймёт)
- Без STT артефактов
- С нормальной пунктуацией
- НЕ переструктурирован в markdown (это работа triage)
- НЕ summarized (это потеря деталей)
- Сохраняющим voice автора

Если cleaned text не похож на raw text по смыслу — agent перестарался, надо откатить и просить более консервативную правку.

## When cleanup is overkill

Если raw text >5000 слов:
- Cleanup может перебрать context budget даже для sub-agent
- Лучше разбить на куски по темам, чистить по очереди
- Или сразу `/triage` который выделит concerns, потом `/cleanup` per-concern

Sub-agent has its own context but не безлимитный.

## Anti-patterns

- ❌ Auto-applying /cleanup без подтверждения пользователя
- ❌ Cleanup как часть `/triage` workflow — это разные задачи, разные skills
- ❌ Удаление оригинала после cleanup
- ❌ Cleanup в основном чате (загрязняет твой контекст) — всегда через sub-agent
- ❌ "Улучшение" текста под видом cleanup — это редактура, не корректура
