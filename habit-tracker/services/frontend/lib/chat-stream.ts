// [review:need-review] PHASE-03/111
// summary: pure parser of the chat SSE stream — frames buffered across network chunks, `event:`/`data:` turned into a discriminated union, and anything unknown skipped instead of thrown

/**
 * One event of a chat turn, as the server names it.
 *
 * A discriminated union rather than an object with optional fields: `usage`
 * and `done` carry different things, and a shape where both are half-empty
 * makes the screen read `event.text` on an event that has none.
 */
export type ChatStreamEvent =
  | { kind: 'delta'; text: string }
  | {
      kind: 'usage';
      inputTokens: number | null;
      outputTokens: number | null;
      cacheReadTokens: number | null;
    }
  | { kind: 'done'; messageId: number; seq: number; status: string }
  | { kind: 'error'; code: string };

/** Frame boundary of SSE. Two newlines end an event, wherever the chunk ended. */
const FRAME_SEPARATOR = '\n\n';

const EVENT_PREFIX = 'event: ';
const DATA_PREFIX = 'data: ';

/** Event names the server sends. Anything else is skipped, not thrown on. */
const EVENT_DELTA = 'delta';
const EVENT_USAGE = 'usage';
const EVENT_DONE = 'done';
const EVENT_ERROR = 'error';

/** JSON object of a frame, before we know which event it belongs to. */
type Payload = Record<string, unknown>;

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function toEvent(name: string, payload: Payload): ChatStreamEvent | null {
  if (name === EVENT_DELTA) {
    const text = asString(payload.text);
    // An empty delta is not an event: it would repaint the bubble for nothing.
    return text ? { kind: 'delta', text } : null;
  }
  if (name === EVENT_USAGE) {
    return {
      kind: 'usage',
      inputTokens: asNumber(payload.input_tokens),
      outputTokens: asNumber(payload.output_tokens),
      cacheReadTokens: asNumber(payload.cache_read_tokens),
    };
  }
  if (name === EVENT_DONE) {
    const messageId = asNumber(payload.message_id);
    const seq = asNumber(payload.seq);
    const status = asString(payload.status);
    if (messageId === null || seq === null || status === null) return null;
    return { kind: 'done', messageId, seq, status };
  }
  if (name === EVENT_ERROR) {
    const code = asString(payload.code);
    return code ? { kind: 'error', code } : null;
  }
  return null;
}

/**
 * One `event:`/`data:` frame as an event, or null when it carries nothing we act on.
 *
 * Multiple `data:` lines are joined with a newline, as the SSE spec says. The
 * server sends one line today; parsing to the spec costs three lines here and
 * saves a silent truncation the day a payload grows.
 */
function parseFrame(frame: string): ChatStreamEvent | null {
  let name: string | null = null;
  const data: string[] = [];
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith(EVENT_PREFIX)) {
      name = line.slice(EVENT_PREFIX.length);
    } else if (line.startsWith(DATA_PREFIX)) {
      data.push(line.slice(DATA_PREFIX.length));
    }
  }
  if (name === null || data.length === 0) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(data.join('\n'));
  } catch {
    // A half-written frame is not an error worth showing the reader: the turn
    // continues, and the text of the answer must never reach the console.
    return null;
  }
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    return null;
  }
  return toEvent(name, payload as Payload);
}

/**
 * Incremental reader of the chat stream.
 *
 * Stateful on purpose: a network chunk ends wherever TCP decided, routinely in
 * the middle of a frame and even in the middle of a UTF-8 word. The leftover
 * lives here, so callers hand over whatever they got and read back the events
 * that are complete.
 */
export class ChatStreamParser {
  private buffer = '';

  /** Events completed by this chunk, in the order they arrived. */
  push(chunk: string): ChatStreamEvent[] {
    this.buffer += chunk;
    const events: ChatStreamEvent[] = [];
    let boundary = this.buffer.indexOf(FRAME_SEPARATOR);
    while (boundary !== -1) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + FRAME_SEPARATOR.length);
      const event = parseFrame(frame);
      if (event) events.push(event);
      boundary = this.buffer.indexOf(FRAME_SEPARATOR);
    }
    return events;
  }

  /**
   * The last frame when the stream ended without its closing blank line.
   *
   * A connection cut mid-turn leaves exactly this, and dropping it would lose
   * the final `done` of a turn that did finish.
   */
  flush(): ChatStreamEvent[] {
    const rest = this.buffer;
    this.buffer = '';
    const event = rest.trim() ? parseFrame(rest) : null;
    return event ? [event] : [];
  }
}
