'use client';
// [review:need-review] PHASE-03/118, PHASE-03/116
// summary: /m/chat screen — the same feed, message field and state as the desktop chat, wrapped in the mobile shell's FullScreenSheet so the bar and the field follow the visual viewport instead of disappearing under the on-screen keyboard

import { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import ChatComposer, { SEND_LABEL } from '@/components/chat/ChatComposer';
import ChatFeed from '@/components/chat/ChatFeed';
import { useChat } from '@/hooks/useChat';
import { conversationIdFrom } from '@/lib/chat-nav';
import { MORE_PATH } from '@/lib/routes';

const SHEET_TITLE = 'Chat';

/** Короче десктопной: на узком экране подсказка занимает пол-экрана. */
const EMPTY_HINT = 'Напиши сообщение — ответ придёт по кускам.';

/** Поле в одну строку в покое: экрана мало, и лента важнее пустого поля. */
const MOBILE_COMPOSER_ROWS = 1;

/**
 * Чат на телефоне.
 *
 * Лист на весь экран, а не обычная страница мобильной оболочки, ровно из-за
 * клавиатуры. iOS не уменьшает layout viewport под клавиатуру — он уменьшает
 * визуальный и прокручивает страницу внутри него, поэтому поле ввода на
 * обычной странице уезжает под клавиатуру вместе с последним сообщением.
 * `FullScreenSheet` уже следит за `visualViewport`, и это единственная причина
 * брать его сюда: своей навигации чат не заводит, в «More» он попадает записью
 * в реестре маршрутов.
 *
 * Отправка есть и в шапке листа, и рядом с полем. Это одно и то же действие:
 * кнопка у поля — привычная для переписки, кнопка в шапке видна всегда, даже
 * когда палец стоит в конце длинной реплики.
 */
function MobileChatScreen() {
  const router = useRouter();
  const conversationId = conversationIdFrom(useSearchParams());
  const {
    screen,
    messages,
    turn,
    draft,
    setDraft,
    send,
    busy,
    canSend,
    reset,
    dismissError,
  } = useChat({ conversationId });

  // Выход из листа — в «More», а не `router.back()`: по ссылке из чужого
  // сообщения истории у вкладки нет, и «назад» в ней никуда не ведёт.
  const close = () => router.push(MORE_PATH);

  if (screen.status === 'loading') return <LoadingSpinner size="lg" />;
  if (screen.status === 'failed') {
    return <ErrorAlert message={screen.message} onDismiss={dismissError} />;
  }

  return (
    <FullScreenSheet
      title={SHEET_TITLE}
      onCancel={close}
      onDone={send}
      doneLabel={SEND_LABEL}
      // `busy` в листе переименовывает действие в «Saving...» — неправда про
      // идущий ход. Пока ход идёт, `canSend` и так ложь, и кнопка выключена
      // без вранья в подписи.
      doneDisabled={!canSend}
    >
      <ChatFeed messages={messages} turn={turn} emptyHint={EMPTY_HINT} onReset={reset} />
      {/* Прилипает ко дну прокручиваемой области листа, а сама область
          повторяет визуальный viewport — поэтому поле стоит прямо над
          клавиатурой, а не под ней. Фон непрозрачный: иначе лента проезжает
          сквозь поле. */}
      <div className="sticky bottom-0 -mx-4 px-4 pb-1 pt-2 bg-background">
        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={send}
          busy={busy}
          canSend={canSend}
          rows={MOBILE_COMPOSER_ROWS}
        />
      </div>
    </FullScreenSheet>
  );
}

export default function MobileChatPage() {
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <MobileChatScreen />
    </Suspense>
  );
}
