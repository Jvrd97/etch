// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today, PHASE-01/43-mobile-dashboard, PHASE-01/47-app-icon-source, PHASE-03/123
// summary: PWA manifest — standalone display launching into the mobile home, which is the mobile Today (#123), dark theme colour, lime check-in-ring icons (any + maskable)

import type { MetadataRoute } from 'next';
import { THEME_COLOR } from '@/lib/theme';
import { MOBILE_HOME } from '@/lib/view-mode';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Habit Tracker',
    short_name: 'Habits',
    description: 'Track your habits, streaks and daily entries',
    start_url: MOBILE_HOME,
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: THEME_COLOR,
    theme_color: THEME_COLOR,
    icons: [
      // `any` for the launcher, `maskable` so Android can crop to its own mask
      // (circle, squircle, ...) without clipping the glyph — the maskable art
      // keeps the icon inside the safe zone, the `any` art fills more of the tile.
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
      { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
