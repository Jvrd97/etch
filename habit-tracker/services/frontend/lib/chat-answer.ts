// [review:need-review] PHASE-03/189
// summary: visibleAnswer — strips the JSON blocks a model addresses to the server (`need` for a retrieval, `plan` for a proposal) out of the text a bubble shows, so the retrieval line and the plan card are the only place either of them appears

/**
 * Ключи верхнего уровня, по которым объект признаётся служебным.
 *
 * `need` — просьба к серверу выполнить именованную выборку; она отражена
 * строкой под ответом. `plan` — предложение записать; оно отражено плашкой с
 * галочками. Ни то, ни другое не адресовано человеку, и печатать их простынёй
 * значит показывать одно и то же дважды, второй раз — нечитаемо.
 */
const SERVICE_KEYS = ['need', 'plan'] as const;

/** Границы одного сбалансированного объекта `{...}` в тексте. */
interface Span {
  start: number;
  end: number;
}

/**
 * Каждый сбалансированный объект в тексте, в порядке появления.
 *
 * Скобки считаются, а не берутся крайние: ответ с двумя объектами иначе
 * склеился бы в один кусок вместе с прозой между ними. Скобка внутри
 * строкового литерала не считается — `"content": "глава про {}"` законная
 * строка плана, а не начало объекта.
 */
function objectSpans(text: string): Span[] {
  const spans: Span[] = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (char === '}' && depth > 0) {
      depth -= 1;
      if (depth === 0) spans.push({ start, end: i + 1 });
    }
  }
  return spans;
}

/** Несёт ли кусок текста объект с одним из служебных ключей. */
function isServiceBlock(raw: string): boolean {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return false;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return false;
  return SERVICE_KEYS.some((key) => key in (parsed as Record<string, unknown>));
}

/**
 * Расширить границы блока на обрамляющий его забор из тройных кавычек.
 *
 * Иначе от вырезанного блока остаются осиротевшие ```` ```json ```` и ```` ``` ````,
 * и пузырь показывает пустой блок кода вместо ничего.
 */
function withFence(text: string, span: Span): Span {
  const before = text.slice(0, span.start);
  const openIndex = before.lastIndexOf('```');
  // Забор считается «этого блока», только если между ним и скобкой нет ничего,
  // кроме имени языка и перевода строки.
  const opensThis = openIndex !== -1 && /^```[a-zA-Z]*\s*$/.test(before.slice(openIndex));
  const after = text.slice(span.end);
  const closeMatch = after.match(/^\s*```/);
  if (!opensThis || closeMatch === null) return span;
  return { start: openIndex, end: span.end + closeMatch[0].length };
}

/**
 * Текст ответа таким, каким его должен видеть человек.
 *
 * Служебные блоки вырезаются вместе с забором, оставшиеся пустые строки
 * схлопываются. Сохранённое сообщение при этом не трогается: в
 * `chat_messages.content` лежит ровно то, что ответила модель, и разбор хода
 * восстанавливается дословно. Экран — не место хранения.
 */
export function visibleAnswer(content: string): string {
  const cuts = objectSpans(content)
    .filter((span) => isServiceBlock(content.slice(span.start, span.end)))
    .map((span) => withFence(content, span));
  if (cuts.length === 0) return content;

  let result = '';
  let cursor = 0;
  for (const cut of cuts) {
    result += content.slice(cursor, cut.start);
    cursor = cut.end;
  }
  result += content.slice(cursor);

  return result.replace(/\n{3,}/g, '\n\n').trim();
}


/**
 * Нёс ли ответ предложение записать.
 *
 * Нужен ровно для одного вопроса экрана: блок плана в ответе был, а плашки под
 * ним нет — значит сервер предложение отверг. Молча вырезать блок и не сказать
 * об этом значит показать «вот план на сегодня» и пустоту под ним; это худший
 * из возможных исходов, потому что выглядит как поломка ленты.
 *
 * Блок `need` планом не считается: он про данные, а не про запись.
 */
export function carriesPlan(content: string): boolean {
  return objectSpans(content).some((span) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(content.slice(span.start, span.end));
    } catch {
      return false;
    }
    return (
      typeof parsed === 'object' &&
      parsed !== null &&
      !Array.isArray(parsed) &&
      'plan' in (parsed as Record<string, unknown>)
    );
  });
}
