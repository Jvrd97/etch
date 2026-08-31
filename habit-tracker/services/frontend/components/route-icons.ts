
// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical, PHASE-03/86, PHASE-03/93, PHASE-03/94, PHASE-03/111, PHASE-03/134, PHASE-03/152
// summary: route id -> lucide icon map (+ the Day summary, Day, Goals, Roles, Chat, Life, Week and Day-rules glyphs) — keeps the UI dependency out of lib/routes so the registry stays importable from server modules

import {
  BookOpen,
  CalendarCheck,
  CalendarDays,
  CalendarRange,
  FolderKanban,
  Gauge,
  Grid3x3,
  Home,
  MessagesSquare,
  MoreHorizontal,
  NotebookPen,
  ScrollText,
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
  life: Grid3x3,
  week: CalendarRange,
  goals: Target,
  roles: Gauge,
  chat: MessagesSquare,
  'day-rules': ScrollText,
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
