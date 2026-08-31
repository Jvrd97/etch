'use client';
// [review:need-review] PHASE-03/111, PHASE-03/112, PHASE-03/113, PHASE-03/117
// summary: /chat screen — the latest conversation is loaded (or started), its stored messages drawn in `seq` order so a restart changes nothing, one turn read through fetch + ReadableStream so the answer appears in pieces instead of all at once at the end, and a badge saying whether the next turn continues the CLI session or rebuilds the dialogue
// summary: PHASE-03/117 puts the spend of the dialogue and of every single turn on the screen, and hangs the delete on the header — after it the screen starts the next conversation instead of showing the one that is gone
// summary: PHASE-03/113 puts the "что чат видит" disclosure under the header, so the day card that went into the prompt can be read back verbatim

import { useCallback, useEffect, useRef, useState } from 'react';
import { MessagesSquare, RefreshCw, RotateCcw, SendHorizonal } from 'lucide-react';
import ChatContextDisclosure from '@/components/chat/ChatContextDisclosure';
import ChatHeader, { type DeleteState } from '@/components/chat/ChatHeader';
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
import { formatTokens, lastCacheRead, resumeMode } from '@/lib/chat-resume';
import type { ChatStreamEvent } from '@/lib/chat-stream';
import { turnCost } from '@/lib/chat-usage';
import { entryInputClass } from '@/lib/ui-constants';

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

/** The turn in flight, if any. `text` grows delta by delta. */
type Turn =
  | { phase: 'idle' }
  | { phase: 'streaming'; question: string; text: string }
  | { phase: 'failed'; question: string; text: string; code: string };

/** What the reader is told when the backend refuses the turn, by machine code. */
const TURN_ERROR_TEXT: Record<string, string> = {
  backend_failed: 'Бэкенд не смог ответить. Ход записан как неудавшийся.',
};

const TURN_ERROR_FALLBACK = 'Ход не удался.';

const EMPTY_HINT = 'Напиши сообщение — ответ придёт по кускам, а не целиком в конце.';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error';
}

function Bubble({ role, children }: { role: string; children: React.ReactNode }) {
  const mine = role === 'user';
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[90%] px-5 py-3.5 rounded-3xl text-sm leading-relaxed ${
          mine
            ? 'bg-lime text-background font-medium'
            : 'bg-card border border-white/5 text-text-primary'
        }`}
      >
        {children}
      </div>
    </div>
  );
}

export default function ChatPage() {
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Одна лента на экран: берётся свежий разговор, а если его нет —
        // заводится. Список разговоров — отдельный срез, не этот.
        const feed = await chatAPI.list(1);
        const conversation = feed[0] ?? (await chatAPI.create());
        const detail = await chatAPI.get(conversation.id);
        if (cancelled) return;
        setMessages(detail.messages);
        setUsage(detail.usage);
        setScreen({
          status: 'ready',
          conversationId: conversation.id,
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
  }, [reloads]);

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
    // осталось.
    setMessages([]);
    setUsage(EMPTY_USAGE);
    setTurn({ phase: 'idle' });
    setRemoval('idle');
    setScreen({ status: 'loading' });
    setReloads((count) => count + 1);
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turn]);

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
      setTurn({ phase: 'streaming', question, text: '' });
      // Held in an object rather than in a `let`: the assignment happens inside
      // a callback, and TypeScript would narrow a plain local to `null` for
      // every line that follows the loop.
      const outcome: { errorCode: string | null } = { errorCode: null };
      try {
        await chatAPI.streamMessage(conversationId, question, (event: ChatStreamEvent) => {
          if (event.kind === 'delta') {
            setTurn((current) =>
              current.phase === 'streaming'
                ? { ...current, text: current.text + event.text }
                : current
            );
          } else if (event.kind === 'error') {
            outcome.errorCode = event.code;
          }
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
    },
    [loadPlans]
  );

  if (screen.status === 'loading') return <LoadingSpinner size="lg" />;
  if (screen.status === 'failed') {
    return (
      <ErrorAlert
        message={screen.message}
        onDismiss={() => setScreen({ status: 'loading' })}
      />
    );
  }

  const busy = turn.phase === 'streaming';
  const mode = resumeMode(screen.resumeReady);
  const cached = lastCacheRead(messages);

  return (
    <div className="space-y-6 animate-fade-rise">
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
          return (
            <Bubble key={message.id} role={message.role}>
              {message.role === 'user' ? (
                <span className="whitespace-pre-wrap">{message.content}</span>
              ) : (
                <Markdown content={message.content} />
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
            </Bubble>
          );
        })}

        {turn.phase !== 'idle' && (
          <>
            <Bubble role="user">
              <span className="whitespace-pre-wrap">{turn.question}</span>
            </Bubble>
            <Bubble role="assistant">
              {turn.text ? (
                <span className="whitespace-pre-wrap">{turn.text}</span>
              ) : (
                <span className="text-text-disabled">…</span>
              )}
              {turn.phase === 'failed' && (
                <p className="mt-2 text-xs text-danger">
                  {TURN_ERROR_TEXT[turn.code] ?? TURN_ERROR_FALLBACK}
                </p>
              )}
            </Bubble>
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
  );
}
