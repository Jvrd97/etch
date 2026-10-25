'use client';
// [review:need-review] 205
// summary: the «Passkey» row of the mobile "More" screen — leads to /m/settings/passkeys and is drawn only while the server has passkey on; `usePasskeyEnabled` is the same check for the desktop drawer row

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, Fingerprint } from 'lucide-react';
import { passkeyAPI } from '@/lib/passkey';
import { TAP_TARGET_PX, navRowClass } from '@/lib/ui-constants';

/** Экраны ключей. Вне реестра экранов: их показывают, только если passkey включён. */
export const MOBILE_PASSKEYS_PATH = '/m/settings/passkeys';
export const DESKTOP_PASSKEYS_PATH = '/settings/passkeys';

/** Включён ли passkey на сервере; до ответа и без ответа — нет. */
export function usePasskeyEnabled(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let alive = true;
    passkeyAPI
      .status()
      .then((status) => {
        if (alive) setEnabled(status.enabled);
      })
      // No answer means no row: the rest of the list does not depend on it.
      .catch(() => {
        if (alive) setEnabled(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  return enabled;
}

export default function PasskeyMoreLink() {
  if (!usePasskeyEnabled()) return null;

  return (
    <Link href={MOBILE_PASSKEYS_PATH} style={{ minHeight: TAP_TARGET_PX }} className={navRowClass}>
      <Fingerprint className="w-5 h-5 text-lime" strokeWidth={2} />
      <span className="flex-1 text-sm font-medium">Passkey</span>
      <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
    </Link>
  );
}
