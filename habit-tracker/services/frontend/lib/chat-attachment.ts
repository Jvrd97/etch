// [review:need-review] PHASE-03/193
// summary: attachToDraft — a dropped text file becomes a labelled block appended to the draft and nothing is stored anywhere; binaries, empty files and anything that would not fit the message ceiling are refused by name with the reason said out loud

/**
 * Потолок реплики. Зеркалит `MESSAGE_MAX_CHARS` из `app/schemas/chat.py`.
 *
 * Второе место, где написано число, — плохо, но выбор здесь между этим и
 * ручкой, отдающей константу ради одного поля. Сервер остаётся тем, кто
 * отказывает: он проверяет длину и отвечает 422. Здесь число нужно, чтобы не
 * дать человеку набрать заведомо обречённую реплику и узнать об этом после
 * отправки.
 */
export const MESSAGE_MAX_CHARS = 100_000;

/**
 * Расширения, которые читаются как слова.
 *
 * Список, а не «всё, что не картинка»: файл, прочитанный как текст по ошибке,
 * приезжает в реплику мусором из байтов и тратит потолок целиком. Браузер
 * называет тип не всегда — у `.md` и `.log` он часто пуст, — поэтому расширение
 * тоже считается признаком.
 */
const TEXT_EXTENSIONS = [
  '.md',
  '.markdown',
  '.txt',
  '.csv',
  '.tsv',
  '.json',
  '.yaml',
  '.yml',
  '.log',
  '.sql',
  '.py',
  '.ts',
  '.tsx',
  '.js',
  '.sh',
];

/** Чем подписан файл в реплике. Ими же его называет модель, отвечая. */
const OPEN = (name: string) => `--- файл ${name} ---`;
const CLOSE = (name: string) => `--- конец ${name} ---`;

export const REFUSED_BINARY = 'это не текстовый файл — я умею только читаемые словами';
export const REFUSED_EMPTY = 'файл пустой — прикладывать нечего';

/** Отказ по размеру называет оба числа: своё и потолок. */
export function refusedTooLong(total: number): string {
  return `не влезает: ${total} знаков против потолка в ${MESSAGE_MAX_CHARS}`;
}

export type AttachOutcome =
  | { status: 'ok'; draft: string }
  | { status: 'refused'; reason: string };

/** Читается ли файл как слова — по типу от браузера или по расширению. */
export function isTextFile(name: string, type: string): boolean {
  if (type.startsWith('text/')) return true;
  const lower = name.toLowerCase();
  return TEXT_EXTENSIONS.some((one) => lower.endsWith(one));
}

/**
 * Дописать файл к реплике — или отказать, назвав причину.
 *
 * Файл нигде не хранится: его текст становится частью реплики и живёт ровно
 * столько, сколько живёт она. Ни ручки загрузки, ни тома, ни таблицы вложений —
 * и удалять потом тоже нечего.
 *
 * Потолок считается по всей реплике, а не по файлу: почти полное поле плюс
 * маленький файл упираются в него так же, как пустое поле плюс огромный.
 * Считать только файл значило бы отдать серверу отказ, которого экран мог
 * избежать.
 */
export function attachToDraft(
  draft: string,
  name: string,
  text: string
): AttachOutcome {
  if (text.trim().length === 0) return { status: 'refused', reason: REFUSED_EMPTY };

  const block = `${OPEN(name)}\n${text.trim()}\n${CLOSE(name)}`;
  const next = draft.trim().length > 0 ? `${draft.trimEnd()}\n\n${block}` : block;
  if (next.length > MESSAGE_MAX_CHARS) {
    return { status: 'refused', reason: refusedTooLong(next.length) };
  }
  return { status: 'ok', draft: next };
}
