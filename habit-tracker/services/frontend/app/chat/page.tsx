'use client';
// [review:need-review] PHASE-03/111, PHASE-03/118
// summary: /chat screen — markup only now: the conversation named by the link (or the latest one), its feed and its message field come from the pieces the mobile screen draws too, so a change to either is a change in one place

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import ChatComposer from '@/components/chat/ChatComposer';
import ChatFeed from '@/components/chat/ChatFeed';
import { useChat } from '@/hooks/useChat';
import { conversationIdFrom } from '@/lib/chat-nav';

const EMPTY_HINT = 'Напиши сообщение — ответ придёт по кускам, а не целиком в конце.';

function ChatScreen() {
  const conversationId = conversationIdFrom(useSearchParams());
  const { screen, messages, turn, draft, setDraft, send, busy, canSend, dismissError } =
    useChat({ conversationId });

  if (screen.status === 'loading') return <LoadingSpinner size="lg" />;
  if (screen.status === 'failed') {
    return <ErrorAlert message={screen.message} onDismiss={dismissError} />;
  }

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
      </div>

      <ChatFeed messages={messages} turn={turn} emptyHint={EMPTY_HINT} />

      <div className="sticky bottom-4">
        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={send}
          busy={busy}
          canSend={canSend}
        />
      </div>
    </div>
  );
}

/**
 * `useSearchParams` заставляет Next отрисовать ветку под ним на клиенте, и без
 * границы `Suspense` это требование поднимается до всей страницы.
 */
export default function ChatPage() {
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <ChatScreen />
    </Suspense>
  );
}
