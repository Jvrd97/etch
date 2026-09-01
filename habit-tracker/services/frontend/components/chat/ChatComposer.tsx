'use client';
// [review:need-review] PHASE-03/118, PHASE-03/192
// summary: the message field both shells use — a textarea whose every keystroke goes to the caller (which mirrors it into the draft) and a send button that is a plain button, not a submit, so the field can sit inside the mobile sheet's own form without nesting one form in another
// summary: PHASE-03/192 makes Enter send and Shift+Enter break the line, and keeps the Enter that closes an IME composition out of it

import { SendHorizonal } from 'lucide-react';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

export interface ChatComposerProps {
  value: string;
  onChange: (text: string) => void;
  /** Отправить. Вызывается только когда `canSend`. */
  onSend: () => void;
  /** True, пока ход идёт: поле заперто, кнопка недоступна. */
  busy: boolean;
  /** True, когда есть что отправить. */
  canSend: boolean;
  /** Сколько строк занимает поле в покое. На узком экране их меньше. */
  rows?: number;
}

export const MESSAGE_FIELD_LABEL = 'Сообщение';
export const SEND_LABEL = 'Отправить';

/** Высота поля в покое на широком экране. */
const DEFAULT_ROWS = 2;

/**
 * Поле ввода реплики — одно на обе оболочки.
 *
 * Не форма и не `type="submit"`. Мобильный экран вкладывает это поле внутрь
 * `FullScreenSheet`, а тот уже форма; вложенная форма — невалидная разметка, и
 * браузер разбирает её так, как ему удобно, а не так, как написано.
 *
 * **Enter отправляет, Shift+Enter переносит строку** (`#192`). Прежде Enter
 * только переносил: поле многострочное, и реплика о дне бывает в три абзаца.
 * Но чат — это переписка, а не форма, и рука ждёт от него привычки переписки;
 * абзацы никуда не делись, они за Shift.
 *
 * Enter, закрывающий композицию IME, отправкой не считается: тем же нажатием
 * подтверждают иероглиф и диакритику, и оно ушло бы недописанным словом.
 * Браузер помечает такое нажатие `isComposing` — другого способа их различить
 * нет.
 */
export default function ChatComposer({
  value,
  onChange,
  onSend,
  busy,
  canSend,
  rows = DEFAULT_ROWS,
}: ChatComposerProps) {
  return (
    <div className="flex items-end gap-3">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' || event.shiftKey) return;
          // `nativeEvent.isComposing` — единственный признак, отличающий Enter
          // отправки от Enter, которым закрывают композицию ввода.
          if (event.nativeEvent.isComposing) return;
          event.preventDefault();
          if (!canSend || busy) return;
          onSend();
        }}
        rows={rows}
        placeholder={MESSAGE_FIELD_LABEL}
        aria-label={MESSAGE_FIELD_LABEL}
        disabled={busy}
        className={`${entryInputClass} resize-none`}
      />
      <button
        type="button"
        onClick={onSend}
        disabled={!canSend}
        aria-label={SEND_LABEL}
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
      >
        <SendHorizonal className="w-4 h-4 shrink-0" strokeWidth={2} />
      </button>
    </div>
  );
}
