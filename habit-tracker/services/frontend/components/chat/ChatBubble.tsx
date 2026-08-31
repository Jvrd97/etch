'use client';
// [review:need-review] PHASE-03/120
// summary: one message bubble, shared by both shells — the accent kept on the reader's own message and off the model's answer, a line length capped at a readable measure instead of the container's width, long unbroken tokens wrapped rather than allowed to widen the row, and the copy button standing under the text instead of over its first line

import CopyButton from '@/components/chat/CopyButton';

export interface ChatBubbleProps {
  role: string;
  /**
   * Чистый текст сообщения для буфера обмена. `null` — копировать нечего
   * (пустой ход, ещё не сказавший ни слова), и кнопки нет.
   */
  copyText?: string | null;
  children: React.ReactNode;
}

/**
 * Пузырь сообщения.
 *
 * **Ширина строки задана буквами, а не процентом контейнера.** Прежние
 * `max-w-[90%]` внутри `max-w-7xl` давали строку под тысячу пикселей: глаз на
 * такой длине теряет начало следующей строки, и длинный ответ читается тяжело
 * независимо от цвета. Потолок стоит в `ch` — это и есть мера читаемости, — а
 * прежние 90% остались вторым ограничением для узкого экрана, где до потолка в
 * буквах дело не доходит.
 *
 * **Акцент остаётся у своей реплики.** Салатовая заливка — это «сказал я», и
 * она работает ровно потому, что ответ модели её не носит: два соседних блока,
 * залитых одинаково ярко, перестают различаться с первого взгляда. Своя реплика
 * при этом обычно короче ответа, и потолок у неё жёстче — длинный текст на
 * сплошном акценте читать тяжело даже в правильной ширине.
 *
 * `break-words` — не косметика: голая ссылка без пробелов внутри `w-fit`
 * растягивала бы строку до края экрана и уносила бы за него разметку соседей.
 *
 * Кнопка копии стоит **под** текстом, отдельной строкой. В углу над первой
 * строкой она отнимала место у самого текста (`pr-12` на каждом пузыре) и на
 * коротких репликах вставала прямо на слова; под текстом она никому не мешает
 * и оказывается там, где взгляд заканчивает чтение.
 */
export default function ChatBubble({ role, copyText = null, children }: ChatBubbleProps) {
  const mine = role === 'user';
  const copyable = copyText !== null && copyText.length > 0;
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`copy-host relative w-fit min-w-0 break-words px-5 py-3.5 rounded-3xl text-sm leading-relaxed ${
          mine ? 'max-w-[min(52ch,90%)]' : 'max-w-[min(68ch,90%)]'
        } ${
          mine
            ? 'bg-lime text-background font-medium'
            : 'bg-card border border-white/5 text-text-primary'
        }`}
      >
        {children}
        {copyable && (
          // Отрицательный отступ снизу гасит запас тап-таргета (44px по
          // `TAP_TARGET_PX`): доступный размер нажатия остаётся, а пустая
          // полоса под коротким сообщением — нет.
          <div className="mt-1 -mb-2 flex justify-end">
            <CopyButton text={copyText} onAccent={mine} />
          </div>
        )}
      </div>
    </div>
  );
}
