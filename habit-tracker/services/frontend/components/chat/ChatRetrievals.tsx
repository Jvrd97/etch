'use client';
// [review:need-review] PHASE-03/114
// summary: the collapsed «запрошено: …» line under an assistant message — what the model pulled and how much of it, expanding to the exact parameters each retrieval ran with

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ChatRetrieval } from '@/lib/api';
import { retrievalSummary, retrievalsHeading } from '@/lib/chat-retrievals';

/**
 * Что модель достала, отвечая этим сообщением.
 *
 * Строка отвечает на единственный вопрос, ради которого заведена таблица
 * `chat_retrievals`: какие мои данные и когда покинули сервер. Поэтому она
 * висит под ответом, а не лежит в базе, — иначе на вопрос отвечал бы `psql`.
 *
 * Раскрытие показывает параметры дословно. Пересказ («за две недели») здесь
 * был бы вторым описанием того же запроса и разошёлся бы с первым: границы
 * запроса — это ровно то, что уехало в базу, а не то, как это удобно назвать.
 *
 * Данных в раскрытии нет и не будет: их нет и в таблице. Строка про размер —
 * это всё, что известно про содержимое, и в этом смысл.
 */

interface Props {
  rows: ChatRetrieval[];
}

export default function ChatRetrievals({ rows }: Props) {
  const [open, setOpen] = useState(false);

  if (rows.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        data-testid="retrievals-toggle"
        className="inline-flex items-start gap-1.5 text-left text-xs text-text-secondary transition-colors hover:text-text-primary"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 mt-0.5 shrink-0" strokeWidth={2} />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 mt-0.5 shrink-0" strokeWidth={2} />
        )}
        <span>{retrievalsHeading(rows)}</span>
      </button>

      {open && (
        <ul className="mt-2 space-y-2" data-testid="retrievals-detail">
          {rows.map((row) => (
            <li key={row.id} className="text-[11px] leading-relaxed">
              <p className="text-text-secondary">{retrievalSummary(row)}</p>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-text-disabled">
                {JSON.stringify(row.params)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
