// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: /m has no screen of its own — send the user to the registry's mobile landing screen

import { redirect } from 'next/navigation';
import { MOBILE_HOME } from '@/lib/view-mode';

export default function MobileIndexPage(): never {
  redirect(MOBILE_HOME);
}
