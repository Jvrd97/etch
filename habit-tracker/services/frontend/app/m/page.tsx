// [review:need-review] PHASE-03/123
// summary: the bare /m is a redirect into the mobile Today — the PWA icon opens the buttons, and the mobile dashboard keeps its own address at /m/dashboard

import { redirect } from 'next/navigation';
import { MOBILE_HOME } from '@/lib/view-mode';

/**
 * `/m` goes to the mobile Today, for the same reason `/` goes to the desktop
 * one: the app is opened to press a button, and the manifest's `start_url`
 * points here through `MOBILE_HOME`.
 */
export default function MobileRootPage(): never {
  redirect(MOBILE_HOME);
}
