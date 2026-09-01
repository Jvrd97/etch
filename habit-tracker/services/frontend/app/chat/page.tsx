'use client';
// [review:need-review] PHASE-03/111, PHASE-03/112, PHASE-03/113, PHASE-03/117, PHASE-03/120
// summary: /chat screen — the latest conversation is loaded (or started), its stored messages drawn in `seq` order so a restart changes nothing, one turn read through fetch + ReadableStream so the answer appears in pieces instead of all at once at the end, and a badge saying whether the next turn continues the CLI session or rebuilds the dialogue
// summary: PHASE-03/117 puts the spend of the dialogue and of every single turn on the screen, and hangs the delete on the header — after it the screen starts the next conversation instead of showing the one that is gone
// summary: PHASE-03/113 puts the "что чат видит" disclosure under the header, so the day card that went into the prompt can be read back verbatim
// summary: PHASE-03/120 gives the wide screen the same live turn as the phone — the model's thought collapsed above the answer, a sign of life before the first word, a caret while it arrives, and a copy button on every message
// summary: PHASE-03/111 puts the history of conversations beside the feed — the one named in `?conversation` is the one that opens, «Новый разговор» starts one and goes there, and the list is re-read after every turn because the title is written from the first question

import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { MessagesSquare, RefreshCw, RotateCcw, SendHorizonal } from 'lucide-react';
import ChatBubble from '@/components/chat/ChatBubble';
import ChatContextDisclosure from '@/components/chat/ChatContextDisclosure';
import ChatHeader, { type DeleteState } from '@/components/chat/ChatHeader';
import ChatHistory from '@/components/chat/ChatHistory';
import ThinkingBlock from '@/components/chat/ThinkingBlock';
import { StreamingCaret, WaitingDots } from '@/components/chat/TurnLive';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import Markdown from '@/components/Markdown';
import ChatPlanCard from '@/components/ChatPlanCard';
import {
  chatAPI,
  type ChatMessage,
  type ChatPlan,
  type ChatPlanSelection,
  type ChatUsage,
} from '@/lib/api';
import { visibleAnswer } from '@/lib/chat-answer';
import { CHAT_PATH, chatHrefFor, conversationIdFrom } from '@/lib/chat-nav';
import { lastCacheRead, resumeMode } from '@/lib/chat-resume';
import { todayISO } from '@/lib/date';
import { useChatHistory } from '@/hooks/useChatHistory';
import { applyProgress, NO_PROGRESS, type TurnProgress } from '@/lib/chat-progress';
import type { ChatStreamEvent } from '@/lib/chat-stream';
import { formatTokens, turnCost } from '@/lib/chat-usage';
import { entryInputClass } from '@/lib/ui-constants';

/**
 * Две колонки на широком экране и одна на узком.
 *
 * История стоит первой в разметке, а не после ленты: порядок чтения с
 * клавиатуры — тот же список, что и глазами, а на узком экране разговор
 * начинается с ответа на вопрос «какой разговор открыт».
 */
const SHELL_CLASS = 'grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)] items-start';

/** Расход разговора, у которого ещё не было ни одного хода. */
const EMPTY_USAGE: ChatUsage = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  message_count: 0,
  latency_ms_median: null,
};

/**
 * What the screen is doing right now.
 *
 * A union rather than three booleans: "loading and failed" and "ready without a
 * conversation" are states a boolean triple can represent and this screen never
 * has.
 */
type Screen =
  | { status: 'loading' }
  | { status: 'failed'; message: string }
  | { status: 'ready'; conversationId: number; resumeReady: boolean };

/**
 * The turn in flight, if any. `text` grows delta by delta.
 *
 * `progress` — второе текстовое поле хода: в `text` копится ответ, во внутренней
 * речи модели живёт `progress.thinking`, и первое никогда не собирается из
 * второго. Граница та же, что на бэкенде, и стоит она здесь по той же причине —
 * чтобы мысль не могла дописаться в пузырь модели.
 */
type Turn =
  | { phase: 'idle' }
  | { phase: 'streaming'; question: string; text: string; progress: TurnProgress }
  | {
      phase: 'failed';
      question: string;
      text: string;
      progress: TurnProgress;
      code: string;
    };

/** What the reader is told when the backend refuses the turn, by machine code. */
const TURN_ERROR_TEXT: Record<string, string> = {
  backend_failed: 'Бэкенд не смог ответить. Ход записан как неудавшийся.',
};

const TURN_ERROR_FALLBACK = 'Ход не удался.';

const EMPTY_HINT = 'Напиши сообщение — ответ придёт по кускам, а не целиком в конце.';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
}

/**
 * Экран разговора вместе с историей всех остальных.
 *
 * Разговор назван адресом (`?conversation=<id>`), а не выбран состоянием: так
 * на него можно дать ссылку, так работает «назад», и так «спросить про день»
 * открывает именно тот разговор, который завело.
 */
function ChatScreen() {
  const router = useRouter();
  const pathname = usePathname();
  // Разговор из ссылки. `null` — «свежий, а нет его — заведи».
  const wanted = conversationIdFrom(useSearchParams());
  const history = useChatHistory();
  const [screen, setScreen] = useState<Screen>({ status: 'loading' });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [usage, setUsage] = useState<ChatUsage>(EMPTY_USAGE);
  const [turn, setTurn] = useState<Turn>({ phase: 'idle' });
  const [removal, setRemoval] = useState<DeleteState>('idle');
  const [draft, setDraft] = useState('');
  const [reloads, setReloads] = useState(0);
  // Планы лентой, по `plan_id` сообщения. Держатся отдельно от сообщений,
  // потому что применение меняет план, а не реплику, под которой он висит.
  const [plans, setPlans] = useState<Record<number, ChatPlan>>({});
  const bottom = useRef<HTMLDivElement | null>(null);
  // Разговор, под который выставлено состояние экрана. Сравнение прямо в
  // рендере — тот самый сброс состояния на смену входа, который React
  // предлагает вместо эффекта: иначе переход на другой разговор оставил бы на
  // экране ленту предыдущего до самого ответа сервера.
  const [shown, setShown] = useState<number | null>(wanted);
  if (shown !== wanted) {
    setShown(wanted);
    setScreen({ status: 'loading' });
    setMessages([]);
    setUsage(EMPTY_USAGE);
    setTurn({ phase: 'idle' });
  }

  /**
   * Подтянуть планы ленты.
   *
   * План читается отдельным запросом, а не приезжает вместе с сообщением:
   * `chat_plans` — это то, чем можно доказать, что применено ровно показанное, и
   * читать его надо из его собственной строки.
   */
  const loadPlans = useCallback(async (feed: ChatMessage[], cancelled = false) => {
    const ids = feed
      .map((message) => message.plan_id)
      .filter((id): id is number => id != null);
    if (ids.length === 0) return;
    const loaded = await Promise.all(ids.map((id) => chatAPI.getPlan(id)));
    if (cancelled) return;
    setPlans((current) => {
      const next = { ...current };
      for (const plan of loaded) next[plan.id] = plan;
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Разговор, названный ссылкой, — если она его называет. Иначе
        // свежий, а нет ни одного — заводится новый.
        const id =
          wanted ?? ((await chatAPI.list(1))[0] ?? (await chatAPI.create())).id;
        const detail = await chatAPI.get(id);
        if (cancelled) return;
        setMessages(detail.messages);
        setUsage(detail.usage);
        setScreen({
          status: 'ready',
          conversationId: id,
          resumeReady: detail.resume_ready,
        });
        await loadPlans(detail.messages, cancelled);
      } catch (error) {
        if (!cancelled) setScreen({ status: 'failed', message: errorText(error) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [wanted, reloads, loadPlans]);

  const remove = useCallback(async (conversationId: number) => {
    setRemoval('deleting');
    try {
      await chatAPI.remove(conversationId);
    } catch (error) {
      setRemoval('idle');
      setScreen({ status: 'failed', message: errorText(error) });
      return;
    }
    // Экран не остаётся на разговоре, которого больше нет: тот же путь, что и
    // при первом заходе, — свежий разговор или новый, если ни одного не
    // осталось. Адрес тоже перестаёт называть удалённый разговор, иначе
    // «обновить страницу» открывало бы 404.
    setMessages([]);
    setUsage(EMPTY_USAGE);
    setTurn({ phase: 'idle' });
    setRemoval('idle');
    setScreen({ status: 'loading' });
    setReloads((count) => count + 1);
    history.reload();
    router.replace(CHAT_PATH);
  }, [history, router]);

  /** Завести разговор и уйти в него: список без перехода — половина действия. */
  const startConversation = useCallback(async () => {
    const started = await history.start();
    if (started !== null) router.push(chatHrefFor(pathname, started));
  }, [history, pathname, router]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turn]);

  const applyPlan = useCallback(
    async (planId: number, selection: ChatPlanSelection) => {
      // Ключ идемпотентности рождается на клиенте и один на попытку: второй тап
      // по той же плашке обязан быть повтором, а не вторым применением.
      const key = `chat-plan-${planId}`;
      const result = await chatAPI.applyPlan(planId, selection, key);
      setPlans((current) => ({ ...current, [result.plan.id]: result.plan }));
    },
    [],
  );

  const dismissPlan = useCallback(async (planId: number) => {
    await chatAPI.dismissPlan(planId);
    const refreshed = await chatAPI.getPlan(planId);
    setPlans((current) => ({ ...current, [refreshed.id]: refreshed }));
  }, []);

  const send = useCallback(
    async (conversationId: number, question: string) => {
      setTurn({ phase: 'streaming', question, text: '', progress: NO_PROGRESS });
      // Held in an object rather than in a `let`: the assignment happens inside
      // a callback, and TypeScript would narrow a plain local to `null` for
      // every line that follows the loop.
      const outcome: { errorCode: string | null } = { errorCode: null };
      try {
        await chatAPI.streamMessage(conversationId, question, (event: ChatStreamEvent) => {
          if (event.kind === 'error') {
            outcome.errorCode = event.code;
            return;
          }
          setTurn((current) => {
            if (current.phase !== 'streaming') return current;
            if (event.kind === 'delta') {
              return { ...current, text: current.text + event.text };
            }
            const progress = applyProgress(current.progress, event);
            return progress === current.progress ? current : { ...current, progress };
          });
        });
      } catch (error) {
        setTurn({ phase: 'idle' });
        setScreen({ status: 'failed', message: errorText(error) });
        return;
      }

      const errorCode = outcome.errorCode;
      if (errorCode !== null) {
        setTurn((current) =>
          current.phase === 'streaming'
            ? { ...current, phase: 'failed', code: errorCode }
            : current
        );
        return;
      }

      // Перечитывание вместо склейки в памяти: строки таблицы и есть разговор,
      // и именно они переживут перезагрузку. Расход приезжает тем же ответом:
      // считает его база, и второй его источник во фронте был бы догадкой.
      const detail = await chatAPI.get(conversationId);
      setMessages(detail.messages);
      setUsage(detail.usage);
      // Признак пересчитывается после каждого хода, а не запоминается один раз:
      // файл сессии может исчезнуть между двумя репликами.
      setScreen({
        status: 'ready',
        conversationId,
        resumeReady: detail.resume_ready,
      });
      // Ответ мог принести предложение: без этого плашка появилась бы только
      // после перезагрузки страницы.
      await loadPlans(detail.messages);
      setTurn({ phase: 'idle' });
      // Заголовок разговору пишет сервер по первой реплике человека, а время
      // последней меняется каждым ходом: список без перечитывания врёт ровно
      // про тот разговор, который сейчас ведут.
      history.reload();
    },
    [history, loadPlans]
  );

  const busy = turn.phase === 'streaming';
  const cached = lastCacheRead(messages);
  // История стоит рядом всегда, в том числе пока лента читается: блок,
  // исчезающий на время запроса, читается как перезагрузка страницы.
  const aside = (
    <ChatHistory
      conversations={history.conversations}
      activeId={screen.status === 'ready' ? screen.conversationId : null}
      today={todayISO()}
      hrefFor={(id) => chatHrefFor(pathname, id)}
      onStart={() => void startConversation()}
      starting={history.starting}
      error={history.error}
    />
  );

  if (screen.status !== 'ready') {
    return (
      <div className={SHELL_CLASS}>
        {aside}
        <div className="min-w-0">
          {screen.status === 'loading' ? (
            <LoadingSpinner size="lg" />
          ) : (
            <ErrorAlert
              message={screen.message}
              onDismiss={() => setScreen({ status: 'loading' })}
            />
          )}
        </div>
      </div>
    );
  }

  const mode = resumeMode(screen.resumeReady);

  return (
    <div className={SHELL_CLASS}>
      {aside}
      <div className="space-y-6 min-w-0 animate-fade-rise">
      <ChatHeader
        usage={usage}
        state={removal}
        onAsk={() => setRemoval('confirming')}
        onCancel={() => setRemoval('idle')}
        onConfirm={() => void remove(screen.conversationId)}
      />

      {/* Значок режима хода живёт на экране, а не в шапке, по той же причине,
          что и раскрывашка: `ChatHeader` рисует данное ему пропсами, а признак
          продолжения пересчитывается после каждого хода. */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          title={mode.hint}
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
            mode.kind === 'resume'
              ? 'bg-lime/15 text-lime'
              : 'bg-surface text-text-secondary'
          }`}
        >
          {mode.kind === 'resume' ? (
            <RefreshCw className="w-3 h-3" strokeWidth={2} />
          ) : (
            <RotateCcw className="w-3 h-3" strokeWidth={2} />
          )}
          {mode.label}
        </span>
        {cached !== null && (
          <span className="text-xs text-text-disabled">
            прошлый ход прочитал из кеша {formatTokens(cached)} токенов
          </span>
        )}
      </div>

      {/* Раскрывашка живёт на экране, а не внутри шапки: `ChatHeader` рисует
          то, что ему дали пропсами, и не ходит в сеть сам. */}
      <ChatContextDisclosure
        conversationId={screen.conversationId}
        load={chatAPI.context}
      />

      <div className="space-y-4">
        {messages.length === 0 && turn.phase === 'idle' && (
          <div className="bg-card border border-white/5 rounded-3xl text-center py-16 px-6">
            <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
              <MessagesSquare className="w-8 h-8 text-text-disabled" strokeWidth={2} />
            </div>
            <p className="text-text-secondary">{EMPTY_HINT}</p>
          </div>
        )}

        {messages.map((message) => {
          const cost = turnCost(message);
          // Служебные блоки — `need` и `plan` — из пузыря вырезаются: первый
          // отражён строкой выборки, второй плашкой под ответом. Сохранённое
          // сообщение при этом цело, режется только показ.
          const shown = visibleAnswer(message.content);
          return (
            <ChatBubble key={message.id} role={message.role} copyText={shown}>
              {message.role === 'user' ? (
                <span className="whitespace-pre-wrap break-words">{shown}</span>
              ) : (
                <Markdown content={shown} />
              )}
              {message.plan_id != null && plans[message.plan_id] && (
                <ChatPlanCard
                  plan={plans[message.plan_id]}
                  onApply={applyPlan}
                  onDismiss={dismissPlan}
                />
              )}
              {cost !== null && (
                <p className="mt-2 text-[11px] text-text-disabled">{cost}</p>
              )}
            </ChatBubble>
          );
        })}

        {turn.phase !== 'idle' && (
          <>
            <ChatBubble role="user" copyText={turn.question}>
              <span className="whitespace-pre-wrap break-words">{turn.question}</span>
            </ChatBubble>
            <ChatBubble role="assistant" copyText={visibleAnswer(turn.text)}>
              <ThinkingBlock progress={turn.progress} answering={turn.text.length > 0} />
              {visibleAnswer(turn.text) ? (
                <span className="whitespace-pre-wrap break-words">
                  {visibleAnswer(turn.text)}
                  {turn.phase === 'streaming' && <StreamingCaret />}
                </span>
              ) : turn.phase === 'streaming' ? (
                <WaitingDots />
              ) : (
                <span className="text-text-disabled">…</span>
              )}
              {turn.phase === 'failed' && (
                <p className="mt-2 text-xs text-danger">
                  {TURN_ERROR_TEXT[turn.code] ?? TURN_ERROR_FALLBACK}
                </p>
              )}
            </ChatBubble>
          </>
        )}
        <div ref={bottom} />
      </div>

      <form
        className="flex items-end gap-3 sticky bottom-4"
        onSubmit={(event) => {
          event.preventDefault();
          const question = draft.trim();
          if (!question || busy) return;
          setDraft('');
          void send(screen.conversationId, question);
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={2}
          placeholder="Сообщение"
          aria-label="Сообщение"
          disabled={busy}
          className={`${entryInputClass} resize-none`}
        />
        <button
          type="submit"
          disabled={busy || draft.trim().length === 0}
          aria-label="Отправить"
          className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
        >
          <SendHorizonal className="w-4 h-4" strokeWidth={2} />
        </button>
        </form>
      </div>
    </div>
  );
}

export default function ChatPage() {
  // `useSearchParams` требует границы Suspense: без неё Next валит сборку всей
  // страницы, а не только куска, который читает адрес.
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <ChatScreen />
    </Suspense>
  );
}
