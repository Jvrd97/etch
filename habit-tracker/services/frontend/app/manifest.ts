// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today, PHASE-01/43-mobile-dashboard
// summary: PWA manifest — standalone display launching into the mobile home (bare /m dashboard), dark theme colour, placeholder lime icons

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
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
  };
}
