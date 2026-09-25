'use client';
// [review:need-review] PHASE-03/203
// summary: the phone's history panel over /m/chat — the desktop list and its loading in a left panel above the chat sheet, a picked row or a new conversation closing it, and the modal contract its role promises: Escape closes only the panel, focus starts and stays inside, the scrim swallows taps meant for the chat underneath

import { useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { X } from 'lucide-react';
import ChatHistory from '@/components/chat/ChatHistory';
import { useChatHistory } from '@/hooks/useChatHistory';
import { chatHrefFor } from '@/lib/chat-nav';
import { todayISO } from '@/lib/date';
import { focusablesIn, trapTab } from '@/lib/focus-trap';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

/** Name of the panel and of the button that opens it: one control, one name. */
export const HISTORY_SHEET_TITLE = 'История чатов';
export const HISTORY_SHEET_CLOSE_LABEL = 'Закрыть историю';

export interface ChatHistorySheetProps {
  /** DOM id, so the opening button can point `aria-controls` at it. */
  id: string;
  /** Conversation the chat sheet shows, marked in the list. */
  activeId: number | null;
  /**
   * Close the panel. Every way out calls it, because handing focus back to the
   * opening button is the caller's job and it has one place to do it.
   */
  onClose: () => void;
}

/**
 * History of conversations on the phone.
 *
 * The same list and the same loading as the desktop column (`ChatHistory`,
 * `useChatHistory`), so titles, days and the unread-versus-empty distinction
 * are spelled once. Mounted only while open, which re-reads the feed on every
 * opening: a title written by the server after the last turn is on the list
 * the moment the list is looked at.
 *
 * Rendered beside the chat sheet, not inside it. The sheet closes the whole
 * chat on Escape through its own key handler, and a panel nested in its
 * subtree would hand that Escape up to it. The listener here sits on
 * `document`, as in the desktop drawer, so Escape still closes the panel after
 * a tap on its padding has moved focus to `body`.
 */
export default function ChatHistorySheet({ id, activeId, onClose }: ChatHistorySheetProps) {
  const router = useRouter();
  const pathname = usePathname();
  const history = useChatHistory();
  const panelRef = useRef<HTMLDivElement>(null);

  // Focus starts on the close button, so the keyboard that opened the panel
  // can dismiss it with the next keystroke.
  useEffect(() => {
    focusablesIn(panelRef.current)[0]?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'Tab') trapTab(event, panelRef.current);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // The panel closes only once the conversation exists: a refused create
  // leaves the reason on the list, and a closed panel would hide it.
  const start = async () => {
    const started = await history.start();
    if (started === null) return;
    onClose();
    router.push(chatHrefFor(pathname, started));
  };

  return (
    <>
      {/* Decorative: covers the chat so a tap beside the panel cannot land on
          a control hidden under it. Escape and the close button are the
          keyboard-reachable ways out. */}
      <div
        data-history-scrim
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-[60] bg-background/70 backdrop-blur-sm animate-scrim-in"
      />

      <div
        id={id}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={HISTORY_SHEET_TITLE}
        className="fixed inset-y-0 left-0 z-[60] flex w-80 max-w-[85vw] flex-col border-r border-white/5 bg-background pt-[env(safe-area-inset-top)] animate-drawer-in"
      >
        <div className="flex items-center justify-between gap-2 px-4 py-2">
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            {HISTORY_SHEET_TITLE}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={HISTORY_SHEET_CLOSE_LABEL}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="-mr-2 inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 hover:bg-white/5 hover:text-text-primary"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <ChatHistory
          layout="panel"
          conversations={history.conversations}
          activeId={activeId}
          today={todayISO()}
          hrefFor={(conversationId) => chatHrefFor(pathname, conversationId)}
          onStart={() => void start()}
          starting={history.starting}
          loading={history.loading}
          error={history.error}
          onRetry={history.reload}
          onPick={onClose}
        />
      </div>
    </>
  );
}
