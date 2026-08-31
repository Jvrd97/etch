// [review:need-review] PHASE-03/123
// summary: the root address is a redirect into Today — the bookmark, the typed host and the app icon all land on the buttons instead of on a dashboard nobody opened the tab for

import { redirect } from 'next/navigation';
import { HOME_PATH } from '@/lib/routes';

/**
 * `/` goes to Today.
 *
 * The cold path is «вкладка открыта, отметить воду», and the dashboard was two
 * clicks of navigation away from the buttons. A redirect rather than rendering
 * Today at the root, so one screen keeps one address: the reader who bookmarks
 * what he is looking at bookmarks `/today`, and the dashboard keeps its own
 * address at `/dashboard` instead of becoming unreachable.
 */
export default function RootPage(): never {
  redirect(HOME_PATH);
}
