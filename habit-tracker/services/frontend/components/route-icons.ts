// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical, PHASE-03/86, PHASE-03/93, PHASE-03/111
// summary: route id -> lucide icon map (+ the Day summary, Day, Goals and Chat glyphs) — keeps the UI dependency out of lib/routes so the registry stays importable from server modules

import {
  BookOpen,
  CalendarCheck,
  CalendarDays,
  MessagesSquare,
  FolderKanban,
  Home,
  MoreHorizontal,
  NotebookPen,
  Sparkles,
  Sun,
  Table2,
  Target,
  Wand2,
  type LucideIcon,
} from 'lucide-react';
import { MORE_ROUTE_ID } from '@/lib/routes';

/**
 * Icon per screen id. Lives beside the components rather than in `lib/routes`
 * because the registry is imported by server-only modules (`app/manifest.ts`),
 * and pulling lucide in there would drag the whole icon set into that bundle.
 */
const ROUTE_ICONS: Record<string, LucideIcon> = {
  dashboard: Home,
  today: Sun,
  day: CalendarCheck,
  goals: Target,
  chat: MessagesSquare,
  'daily-summary': NotebookPen,
  table: Table2,
  categories: FolderKanban,
  entries: CalendarDays,
  journal: BookOpen,
  insights: Sparkles,
  onboarding: Wand2,
  [MORE_ROUTE_ID]: MoreHorizontal,
};

/** Icon for a screen id, falling back to the "More" glyph for unknown ids. */
export function routeIcon(id: string): LucideIcon {
  return ROUTE_ICONS[id] ?? MoreHorizontal;
}
