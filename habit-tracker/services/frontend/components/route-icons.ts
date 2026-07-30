// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: route id -> lucide icon map — keeps the UI dependency out of lib/routes so the registry stays importable from server modules

import {
  BookOpen,
  CalendarDays,
  FolderKanban,
  Home,
  MoreHorizontal,
  Sparkles,
  Sun,
  Table2,
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
