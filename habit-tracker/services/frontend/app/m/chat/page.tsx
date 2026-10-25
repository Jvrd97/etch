'use client';
// [review:need-review] PHASE-03/118, PHASE-03/116, PHASE-03/203, PHASE-03/197
// summary: PHASE-03/197 wires deletion from the history panel to this screen — deleting the open conversation leaves the screen on «nothing selected» with its address cleared and no new conversation made, deleting another changes nothing here, and the open conversation with an answer running is not offered for deletion
// summary: PHASE-03/203 puts the history button left of the message field and opens the history panel from it; the sheet now stays up while a conversation loads or fails, so the button and the panel's focus target survive a switch
// summary: /m/chat screen — the same feed, message field and state as the desktop chat, wrapped in the mobile shell's FullScreenSheet so the bar and the field follow the visual viewport instead of disappearing under the on-screen keyboard

import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { History } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import ChatComposer, { SEND_LABEL } from '@/components/chat/ChatComposer';
import ChatFeed from '@/components/chat/ChatFeed';
import { NOTHING_SELECTED } from '@/components/chat/ChatHistory';
import ChatHistorySheet, { HISTORY_SHEET_TITLE } from '@/components/chat/ChatHistorySheet';
import { useChat } from '@/hooks/useChat';
import { useDeletedConversation } from '@/hooks/useDeletedConversation';
import { REMOVE_RUNNING_ANSWER } from '@/hooks/useChatHistory';
import { chatPathFor, conversationIdFrom } from '@/lib/chat-nav';
import { MORE_PATH } from '@/lib/routes';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

const SHEET_TITLE = 'Chat';

/** Короче десктопной: на узком экране подсказка занимает пол-экрана. */
const EMPTY_HINT = 'Напиши сообщение — ответ придёт по кускам.';

/** Поле в одну строку в покое: экрана мало, и лента важнее пустого поля. */
const MOBILE_COMPOSER_ROWS = 1;

const HISTORY_PANEL_ID = 'chat-history-panel';

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
 *
 * История разговоров открывается кнопкой слева от поля (`#203`): она едет над
 * клавиатурой вместе с полем и не заперта на время хода — открыть другой
 * разговор посреди ответа можно. Лист при этом стоит всегда, и пока разговор
 * читается, и когда чтение провалилось: иначе переключение разговора снимало бы
 * вместе с листом и кнопку, в которую должен вернуться фокус, а из разговора,
 * который не открылся, некуда было бы уйти в другой.
 *
 * Удалённый из панели открытый разговор экран не заменяет другим (`#197`): адрес
 * очищается, лист остаётся на «разговор не выбран», а следующий человек выбирает
 * сам. Свежий или новый разговор, открытый молча, выглядел бы как подмена.
 */
function MobileChatScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const {
    conversationId,
    stayEmpty,
    markDeleted,
  } = useDeletedConversation(conversationIdFrom(useSearchParams()));
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
  } = useChat({ conversationId, startWhenMissing: !stayEmpty });
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyButton = useRef<HTMLButtonElement>(null);

  // Выход из листа — в «More», а не `router.back()`: по ссылке из чужого
  // сообщения истории у вкладки нет, и «назад» в ней никуда не ведёт.
  const close = () => router.push(MORE_PATH);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    historyButton.current?.focus();
  }, []);

  const ready = screen.status === 'ready';
  const openId = ready ? screen.conversationId : conversationId;

  // Удаление отвечает, когда человек мог уже открыть другой разговор: решает
  // тот, что открыт в момент ответа, а не тот, что был открыт при нажатии.
  const openIdNow = useRef(openId);
  useEffect(() => {
    openIdNow.current = openId;
  }, [openId]);

  const handleDeleted = useCallback(
    (removedId: number) => {
      if (removedId !== openIdNow.current) return;
      markDeleted(removedId);
      router.replace(chatPathFor(pathname));
    },
    [markDeleted, pathname, router]
  );

  const deleteBlockedReason = (id: number) =>
    id === openId && busy ? REMOVE_RUNNING_ANSWER : null;

  return (
    <>
      <FullScreenSheet
        title={SHEET_TITLE}
        onCancel={close}
        onDone={send}
        doneLabel={SEND_LABEL}
        // `busy` в листе переименовывает действие в «Saving...» — неправда про
        // идущий ход. Пока ход идёт, `canSend` и так ложь, и кнопка выключена
        // без вранья в подписи.
        doneDisabled={!canSend}
        error={screen.status === 'failed' ? screen.message : null}
        onDismissError={dismissError}
      >
        {/* Колонка не ниже листа: при короткой ленте поле и кнопка истории
            стоят внизу экрана, а не сразу под последним сообщением. */}
        <div className="flex min-h-full flex-col gap-5">
          <div className="flex-1">
            {screen.status === 'loading' && <LoadingSpinner size="lg" />}
            {ready && (
              <ChatFeed messages={messages} turn={turn} emptyHint={EMPTY_HINT} onReset={reset} />
            )}
            {screen.status === 'empty' && (
              <p className="py-16 text-center text-text-secondary">{NOTHING_SELECTED}</p>
            )}
          </div>
          {/* Прилипает ко дну прокручиваемой области листа, а сама область
              повторяет визуальный viewport — поэтому поле стоит прямо над
              клавиатурой, а не под ней. Фон непрозрачный: иначе лента проезжает
              сквозь поле. */}
          <div className="sticky bottom-0 -mx-4 px-4 pb-1 pt-2 bg-background">
            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSend={send}
              // Набирать, пока разговор не открыт, некуда: черновик пишется под
              // id разговора, и набранное до его ответа затёр бы прочитанный.
              busy={busy || !ready}
              canSend={canSend}
              rows={MOBILE_COMPOSER_ROWS}
              leading={
                <button
                  ref={historyButton}
                  type="button"
                  onClick={() => setHistoryOpen(true)}
                  aria-label={HISTORY_SHEET_TITLE}
                  aria-haspopup="dialog"
                  aria-expanded={historyOpen}
                  aria-controls={historyOpen ? HISTORY_PANEL_ID : undefined}
                  style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
                  className="inline-flex shrink-0 items-center justify-center rounded-3xl bg-surface text-text-secondary transition-colors duration-200 hover:text-text-primary"
                >
                  <History className="w-5 h-5" strokeWidth={2} />
                </button>
              }
            />
          </div>
        </div>
      </FullScreenSheet>
      {historyOpen && (
        <ChatHistorySheet
          id={HISTORY_PANEL_ID}
          activeId={openId}
          onClose={closeHistory}
          onDeleted={handleDeleted}
          deleteBlockedReason={deleteBlockedReason}
        />
      )}
    </>
  );
}

export default function MobileChatPage() {
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <MobileChatScreen />
    </Suspense>
  );
}
