'use client';
// [review:need-review] PHASE-03/118
// summary: the "ask about the day" entry point on both Today screens — starts a conversation carrying the date of the screen the reader is looking at (never the server's idea of today) and opens it in the shell the reader is already in

import { useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { MessagesSquare } from 'lucide-react';
import { chatAPI } from '@/lib/api';
import { chatHrefFor } from '@/lib/chat-nav';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export interface AskAboutDayButtonProps {
  /**
   * День экрана в виде `YYYY-MM-DD`.
   *
   * Передаётся явно, а не берётся сервером по умолчанию: экран дня открывают и
   * за третье августа, и разговор о нём обязан быть привязан к третьему
   * августа, а не к сегодняшнему числу.
   */
  date: string;
  /** Классы обёртки: на телефоне кнопка во всю ширину, на десктопе — нет. */
  className?: string;
  onError: (message: string) => void;
}

export const ASK_ABOUT_DAY_LABEL = 'Спросить про день';

const BUSY_LABEL = 'Открываю…';

const BASE_CLASS =
  'inline-flex items-center justify-center gap-2 px-6 py-3 bg-card border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:bg-white/5 disabled:opacity-40';

/**
 * Вход в чат с экрана дня.
 *
 * Здесь чат перестаёт быть отдельным разделом: разговор заводится о конкретном
 * дне и открывается сразу, вместо «зайди в More, найди чат, вспомни, о чём
 * спрашивал».
 *
 * Один компонент на обе оболочки, и маршрут он выбирает по текущему пути:
 * кнопка, нажатая в `/m/today`, обязана привести в `/m/chat`, иначе телефон
 * без предупреждения выпадает в десктопную вёрстку.
 */
export default function AskAboutDayButton({
  date,
  className,
  onError,
}: AskAboutDayButtonProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);

  const open = async () => {
    setBusy(true);
    try {
      const conversation = await chatAPI.create({ started_on: date, kind: 'general' });
      router.push(chatHrefFor(pathname, conversation.id));
    } catch (error) {
      // Кнопка возвращается в исходное состояние только на неудаче: на удаче
      // экран уже уезжает, и «Открываю…» — правда до самого перехода.
      setBusy(false);
      onError(error instanceof Error ? error.message : 'Не удалось открыть разговор');
    }
  };

  return (
    <button
      type="button"
      onClick={() => void open()}
      disabled={busy}
      aria-label={ASK_ABOUT_DAY_LABEL}
      style={{ minHeight: TAP_TARGET_PX }}
      className={className ? `${BASE_CLASS} ${className}` : BASE_CLASS}
    >
      <MessagesSquare className="w-4 h-4 shrink-0" strokeWidth={2} />
      {busy ? BUSY_LABEL : ASK_ABOUT_DAY_LABEL}
    </button>
  );
}
