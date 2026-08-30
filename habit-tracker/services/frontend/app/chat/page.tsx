'use client';
// [review:need-review] PHASE-03/111, PHASE-03/112
// summary: /chat screen — the latest conversation is loaded (or started), its stored messages drawn in `seq` order so a restart changes nothing, one turn read through fetch + ReadableStream so the answer appears in pieces instead of all at once at the end, and a header badge saying whether the next turn continues the CLI session or rebuilds the dialogue

import { useCallback, useEffect, useRef, useState } from 'react';
import { MessagesSquare, RefreshCw, RotateCcw, SendHorizonal } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import Markdown from '@/components/Markdown';
import { chatAPI, type ChatMessage } from '@/lib/api';
import { formatTokens, lastCacheRead, resumeMode } from '@/lib/chat-resume';
import type { ChatStreamEvent } from '@/lib/chat-stream';
import { entryInputClass } from '@/lib/ui-constants';

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
  const [turn, setTurn] = useState<Turn>({ phase: 'idle' });
  const [draft, setDraft] = useState('');
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
        setScreen({
          status: 'ready',
          conversationId: conversation.id,
          resumeReady: detail.resume_ready,
        });
      } catch (error) {
        if (!cancelled) setScreen({ status: 'failed', message: errorText(error) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, turn]);

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
      // и именно они переживут перезагрузку.
      const detail = await chatAPI.get(conversationId);
      setMessages(detail.messages);
      // Признак пересчитывается после каждого хода, а не запоминается один раз:
      // файл сессии может исчезнуть между двумя репликами.
      setScreen({
        status: 'ready',
        conversationId,
        resumeReady: detail.resume_ready,
      });
      setTurn({ phase: 'idle' });
    },
    []
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
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Chat
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Разговор о дне. История живёт на сервере и переживает перезапуск.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
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
      </div>

      <div className="space-y-4">
        {messages.length === 0 && turn.phase === 'idle' && (
          <div className="bg-card border border-white/5 rounded-3xl text-center py-16 px-6">
            <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
              <MessagesSquare className="w-8 h-8 text-text-disabled" strokeWidth={2} />
            </div>
            <p className="text-text-secondary">{EMPTY_HINT}</p>
          </div>
        )}

        {messages.map((message) => (
          <Bubble key={message.id} role={message.role}>
            {message.role === 'user' ? (
              <span className="whitespace-pre-wrap">{message.content}</span>
            ) : (
              <Markdown content={message.content} />
            )}
          </Bubble>
        ))}

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
