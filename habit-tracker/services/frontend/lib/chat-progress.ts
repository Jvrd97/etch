// [review:need-review] PHASE-03/120
// summary: what the model is busy with right now, folded out of the turn's step events — the current activity, the words of the thought (empty on the CLI subscription) and the estimated volume, plus the one line the collapsed block shows

import { queryLabel } from '@/lib/chat-retrievals';
import type { ChatStreamEvent } from '@/lib/chat-stream';
import { formatTokens } from '@/lib/chat-usage';

/**
 * Ход мысли как состояние, а не как разметка.
 *
 * Отдельный модуль по той же причине, что и `chat-retrievals`: строка «модель
 * сейчас читает карточку дня» — это ответ на вопрос человека «оно вообще
 * работает?», и он обязан проверяться тестом, а не читаться глазами в JSX.
 *
 * Слова мысли живут здесь и нигде больше: они не пишутся в базу, не идут в
 * лог и не склеиваются в текст ответа. Поле `thinking` — отдельное от текста
 * ответа на всех трёх слоях (кусок бэкенда, событие потока, это состояние),
 * чтобы «мысль дописалась в пузырь модели» было невозможно, а не маловероятно.
 */

/** Чем модель занята прямо сейчас. */
export type TurnActivity =
  | { kind: 'thinking' }
  | { kind: 'acting'; tool: string | null }
  | { kind: 'retrieving'; queryName: string }
  | { kind: 'writing' };

export interface TurnProgress {
  /** Последний названный шаг; `null` — бэкенд шагов не называет вовсе. */
  activity: TurnActivity | null;
  /** Склейка слов мысли. На подписке CLI всегда пустая — см. модуль выше. */
  thinking: string;
  /** Оценка объёма мысли в токенах, когда бэкенд её прислал. */
  thinkingTokens: number | null;
}

/** Ход, о котором ещё ничего не сказано. Общая ссылка: сравнивается по `===`. */
export const NO_PROGRESS: TurnProgress = {
  activity: null,
  thinking: '',
  thinkingTokens: null,
};

export const THINKING_LABEL = 'думает';
export const WRITING_LABEL = 'пишет ответ';

/** Инструмент, имя которого бэкенд не назвал. */
export const UNNAMED_TOOL_LABEL = 'взялся за инструмент';

/**
 * Имена инструментов CLI по-русски.
 *
 * Незнакомое имя показывается как есть — по правилу `chat-retrievals`: экран,
 * молчащий про новый инструмент, хуже экрана с английским словом.
 *
 * Сегодня ни одно из них не приезжает: чат запускает CLI с `--tools ""`, и
 * блока `tool_use` в потоке не бывает. Карта заведена не про запас, а потому
 * что событие `acting` уже проведено до браузера, и день, когда инструмент
 * разрешат, не должен начинаться с «модель делает что-то, чему нет названия».
 */
export const TOOL_LABELS: Record<string, string> = {
  Read: 'читает файл',
  Grep: 'ищет в записях',
  Glob: 'ищет файлы',
  Bash: 'выполняет команду',
  WebSearch: 'ищет в сети',
  WebFetch: 'читает страницу',
};

/** Что показывается в раскрытом блоке, когда слов мысли не приехало. */
export const THINKING_WORDLESS =
  'Слов мысли бэкенд не прислал — видно только, что модель думала.';

/**
 * Событие потока, сложенное в состояние хода.
 *
 * Возвращает тот же объект, когда событие ничего не меняет: `delta` приходит
 * десятками в секунду, и новый объект на каждую из них перерисовывал бы
 * свёрнутый блок впустую.
 *
 * `stepEnd` намеренно ничего не гасит. Блок закрылся — это не «модель ничем не
 * занята»: между двумя блоками проходят миллисекунды, и подпись, мигающая в
 * пустоту и обратно, читается хуже, чем подпись, которая держится до следующего
 * названного шага.
 */
export function applyProgress(
  progress: TurnProgress,
  event: ChatStreamEvent
): TurnProgress {
  switch (event.kind) {
    case 'thinking':
      return {
        activity: { kind: 'thinking' },
        thinking: progress.thinking + event.thinking,
        thinkingTokens: event.thinkingTokens ?? progress.thinkingTokens,
      };
    case 'writing':
      return { ...progress, activity: { kind: 'writing' } };
    case 'acting':
      return { ...progress, activity: { kind: 'acting', tool: event.tool } };
    case 'retrieval':
      // Выборка — тоже занятость, и самая долгая из всех: сорок секунд на
      // `entries_range` иначе неотличимы от зависшего бэкенда.
      return { ...progress, activity: { kind: 'retrieving', queryName: event.queryName } };
    case 'stop':
      return event.thinkingTokens === null
        ? progress
        : { ...progress, thinkingTokens: event.thinkingTokens };
    default:
      return progress;
  }
}

/** Есть ли о чём рисовать блок. Пустой ход не показывает ничего. */
export function hasProgress(progress: TurnProgress): boolean {
  return (
    progress.activity !== null ||
    progress.thinking.length > 0 ||
    progress.thinkingTokens !== null
  );
}

/** Занятость одной строкой — то, что читается в свёрнутом виде. */
export function activityLabel(progress: TurnProgress): string {
  const activity = progress.activity;
  // Шагов нет, а объём мысли приехал: бэкенд успел сказать только «думал».
  if (activity === null) return THINKING_LABEL;
  switch (activity.kind) {
    case 'thinking':
      return THINKING_LABEL;
    case 'writing':
      return WRITING_LABEL;
    case 'retrieving':
      return `читает: ${queryLabel(activity.queryName)}`;
    case 'acting':
      if (activity.tool === null) return UNNAMED_TOOL_LABEL;
      return TOOL_LABELS[activity.tool] ?? `работает: ${activity.tool}`;
  }
}

/**
 * Объём мысли словами, либо `null`, когда его не оценивали.
 *
 * Со знаком «примерно»: бэкенд отдаёт `estimated_tokens`, и число здесь —
 * оценка CLI, а не счётчик расхода. Выдавать её за расход значило бы завести на
 * экране второй, врущий источник цены хода.
 */
export function thinkingVolume(progress: TurnProgress): string | null {
  if (progress.thinkingTokens === null) return null;
  return `~${formatTokens(progress.thinkingTokens)} токенов мысли`;
}
