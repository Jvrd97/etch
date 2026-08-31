'use client';
// [review:need-review] PHASE-03/120
// summary: the copy button of one chat message — writes the plain text of the message to the clipboard, says «Скопировано» for a moment afterwards, and stays silent when the browser refuses the clipboard instead of claiming a copy that did not happen

import { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export const COPY_LABEL = 'Скопировать';
export const COPIED_LABEL = 'Скопировано';

/** Сколько держится подтверждение. Дольше — и оно переживёт следующее нажатие. */
const FEEDBACK_MS = 1600;

export interface CopyButtonProps {
  /** Чистый текст сообщения. Разметки интерфейса в нём нет и быть не должно. */
  text: string;
  /** True у своей реплики: пузырь залит акцентом, и значок на нём тёмный. */
  onAccent?: boolean;
}

/**
 * Скопировать сообщение.
 *
 * Копируется то, что человек считает сообщением: его собственная реплика или
 * текст ответа модели — исходный, до разметки. Пометки экрана (что запрошено,
 * во сколько обошёлся ход, «ответ оборван») в буфер не идут: это подписи ленты,
 * а не сказанное в разговоре.
 *
 * Кнопка не пропадает при отказе буфера, но и не врёт: в незащищённом
 * происхождении или без разрешения `writeText` бросает, и тогда состояние
 * просто не меняется. Показать «скопировано» там, где не скопировалось, —
 * худший из возможных исходов: человек уйдёт вставлять пустоту.
 */
export default function CopyButton({ text, onAccent = false }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    []
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Буфер закрыт браузером — не поломка экрана и не то, о чём стоит писать
      // в консоль: текст сообщения виден, и его можно выделить руками.
      return;
    }
    if (timer.current !== null) clearTimeout(timer.current);
    setCopied(true);
    timer.current = setTimeout(() => setCopied(false), FEEDBACK_MS);
  };

  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? COPIED_LABEL : COPY_LABEL}
      title={copied ? COPIED_LABEL : COPY_LABEL}
      style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
      className={`copy-affordance absolute top-0.5 right-0.5 inline-flex items-center justify-center rounded-2xl ${
        onAccent
          ? 'text-background/50 hover:text-background'
          : 'text-text-disabled hover:text-text-primary'
      }`}
    >
      {copied ? (
        <Check className="w-3.5 h-3.5" strokeWidth={2} />
      ) : (
        <Copy className="w-3.5 h-3.5" strokeWidth={2} />
      )}
    </button>
  );
}
