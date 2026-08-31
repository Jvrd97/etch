// [review:need-review] PHASE-03/142
// summary: the map of the day beside the plan — hard edges with the hours of the rule row, the free evening that is not filled in, the evening with the family, the ceilings of the generator and the formula of the verdict; every number arrives from the server, none is written here

import { Clock, HeartHandshake, Moon } from 'lucide-react';
import type { DayMap } from '@/lib/api';
import {
  FREE_EVENING_HINT,
  edgeLines,
  formatMinutes,
  intervalText,
  relationshipEveningText,
  verdictFormulaText,
} from '@/lib/day-format';

export const MAP_TITLE = 'Карта дня';
export const FREE_EVENING_TITLE = 'Свободный вечер';
export const RELATIONSHIP_TITLE = 'Вечер с близкими';
export const FORMULA_TITLE = 'День снимают, по порядку';

export interface DayMapCardProps {
  map: DayMap;
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/**
 * Where the day's hard points stand, and which stretch of it stays unwritten.
 *
 * Until `#142` this map lived only in `config.md`: the plan could be read, but
 * not compared with the shape the day is supposed to have. Every value below is
 * a column of the `day_rule_set` row the day is judged by, so a new canon moves
 * this card without a line of markup changing — which is the whole reason the
 * numbers are not here.
 */
export default function DayMapCard({ map, compact = false }: DayMapCardProps) {
  const edges = edgeLines(map);

  return (
    <section
      className={`bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`}
    >
      <div className="flex items-center gap-2">
        <Clock
          className={compact ? 'w-4 h-4' : 'w-5 h-5'}
          strokeWidth={2}
          aria-hidden="true"
        />
        <h2
          className={`font-semibold text-text-primary ${compact ? 'text-base' : 'text-xl'}`}
        >
          {MAP_TITLE}
        </h2>
      </div>

      <ul className={compact ? 'mt-3 space-y-2' : 'mt-4 space-y-2.5'}>
        {edges.map((edge) => (
          <li
            key={edge.kind}
            className="flex justify-between gap-4 text-sm"
            data-testid={`edge-${edge.kind}`}
          >
            <span className="text-text-secondary">{edge.label}</span>
            <span className="font-mono text-text-primary text-right">
              {edge.value}
            </span>
          </li>
        ))}
      </ul>

      <div
        className={`mt-4 pt-4 border-t border-white/5 space-y-3 ${compact ? 'text-sm' : ''}`}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="inline-flex items-center gap-2 text-text-secondary">
            <Moon className="w-4 h-4" strokeWidth={2} aria-hidden="true" />
            {FREE_EVENING_TITLE}
          </span>
          <span className="text-text-primary text-right">
            <span className="font-mono">{intervalText(map.free_evening)}</span>{' '}
            <span className="text-text-secondary">{FREE_EVENING_HINT}</span>
          </span>
        </div>

        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="inline-flex items-center gap-2 text-text-secondary">
            <HeartHandshake
              className="w-4 h-4"
              strokeWidth={2}
              aria-hidden="true"
            />
            {RELATIONSHIP_TITLE}
          </span>
          <span className="text-text-primary text-right">
            {relationshipEveningText(map)}
          </span>
        </div>
      </div>

      <dl
        className={`mt-4 pt-4 border-t border-white/5 grid gap-x-8 gap-y-2 text-sm ${
          compact ? '' : 'sm:grid-cols-2'
        }`}
      >
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Рабочих задач</dt>
          <dd className="text-text-primary">не больше {map.max_work_tasks}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Учебных пунктов</dt>
          <dd className="text-text-primary">не больше {map.max_study_items}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Не планировать сверх</dt>
          <dd className="text-text-primary">
            {formatMinutes(map.overtime_lost_min)}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-text-secondary">Якоря</dt>
          <dd className="text-text-primary text-right">
            {map.anchors.join(', ')}
          </dd>
        </div>
        <div className="flex justify-between gap-4 sm:col-span-2">
          <dt className="text-text-secondary">{FORMULA_TITLE}</dt>
          <dd className="text-text-primary text-right">
            {verdictFormulaText(map)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
