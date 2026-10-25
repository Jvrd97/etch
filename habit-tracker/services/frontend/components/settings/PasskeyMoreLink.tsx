'use client';
// [review:need-review] 205
// summary: the «Passkey» row of the mobile "More" screen — leads to /m/settings/passkeys and is drawn only while the server has passkey on

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, Fingerprint } from 'lucide-react';
import { passkeyAPI } from '@/lib/passkey';
import { TAP_TARGET_PX, navRowClass } from '@/lib/ui-constants';

/** Мобильный экран ключей. Вне реестра экранов: его показывают, только если passkey включён. */
export const MOBILE_PASSKEYS_PATH = '/m/settings/passkeys';

export default function PasskeyMoreLink() {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let alive = true;
    passkeyAPI
      .status()
      .then((status) => {
        if (alive) setEnabled(status.enabled);
      })
      // No answer means no row: the rest of "More" does not depend on it.
      .catch(() => setEnabled(false));
    return () => {
      alive = false;
    };
  }, []);

  if (!enabled) return null;

  return (
    <Link href={MOBILE_PASSKEYS_PATH} style={{ minHeight: TAP_TARGET_PX }} className={navRowClass}>
      <Fingerprint className="w-5 h-5 text-lime" strokeWidth={2} />
      <span className="flex-1 text-sm font-medium">Passkey</span>
      <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
    </Link>
  );
}
