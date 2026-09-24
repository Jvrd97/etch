'use client';
// [review:need-review] #76
// summary: renders tracker and journal activity rows, grouped by the day they belong to or labelled by their time or day

import Link from 'next/link';
import { BookText, Calendar, type LucideIcon } from 'lucide-react';
import type { Category, Entry } from '@/lib/api';
import {
  activityTime,
  activityWhen,
  groupActivityFeed,
  type ActivityFeedItem,
} from '@/lib/activity-feed';
import { labelledValues } from '@/lib/entry-values';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import type { ReactNode } from 'react';

interface ActivityFeedProps {
  items: ActivityFeedItem[];
  categories: Category[];
  grouped?: boolean;
  mobile?: boolean;
  renderEntry?: (entry: Entry) => ReactNode;
}

function ActivityRow({
  item,
  categories,
  grouped,
  mobile,
  renderEntry,
}: {
  item: ActivityFeedItem;
  categories: Category[];
  grouped: boolean;
  mobile: boolean;
  renderEntry?: (entry: Entry) => ReactNode;
}) {
  // Under a day heading the day is already said, so the row keeps the time it
  // was written; without one the row has to say which day it is about.
  const when = grouped
    ? { dateTime: item.createdAt, label: activityTime(item.createdAt) }
    : activityWhen(item);

  if (item.kind === 'entry' && renderEntry !== undefined) {
    return (
      <div>
        <time className="mb-2 block text-xs text-text-disabled" dateTime={when.dateTime}>
          {when.label}
        </time>
        {renderEntry(item.entry)}
      </div>
    );
  }

  let href: string;
  let Icon: LucideIcon;
  let title: string;
  let detail: string;
  if (item.kind === 'entry') {
    const category = categories.find(({ id }) => id === item.entry.category_id);
    href = `/entries/${item.entry.id}`;
    Icon = Calendar;
    title = category?.name ?? 'Unknown category';
    detail =
      labelledValues(category, item.entry)
        .map(({ label, value }) => `${label}: ${value}`)
        .join(' · ') || 'No values';
  } else {
    href = '/journal';
    Icon = BookText;
    title = `Journal · ${item.journal.title || 'Day reflection'}`;
    detail = item.journal.content || 'Journal entry';
  }

  return (
    <Link
      href={href}
      style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
      className="flex items-center gap-3 py-3"
    >
      <div className="p-2.5 rounded-2xl bg-surface flex-shrink-0">
        <Icon className="w-4 h-4 text-lime" strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary truncate">{title}</p>
        <p className="text-xs text-text-secondary mt-0.5 truncate">{detail}</p>
      </div>
      <time className="text-xs text-text-disabled flex-shrink-0" dateTime={when.dateTime}>
        {when.label}
      </time>
    </Link>
  );
}

export default function ActivityFeed({
  items,
  categories,
  grouped = false,
  mobile = false,
  renderEntry,
}: ActivityFeedProps) {
  if (!grouped) {
    return (
      <div className="divide-y divide-white/5">
        {items.map((item) => (
          <ActivityRow
            key={item.key}
            item={item}
            categories={categories}
            grouped={false}
            mobile={mobile}
            renderEntry={renderEntry}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {groupActivityFeed(items).map((group) => (
        <section key={group.date} aria-label={group.label}>
          <h2 className="mb-2 text-xs font-medium uppercase tracking-widest text-lime">
            {group.label}
          </h2>
          <div className="divide-y divide-white/5">
            {group.items.map((item) => (
              <ActivityRow
                key={item.key}
                item={item}
                categories={categories}
                grouped
                mobile={mobile}
                renderEntry={renderEntry}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
