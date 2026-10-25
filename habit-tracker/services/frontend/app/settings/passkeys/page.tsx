'use client';
// [review:need-review] 205
// summary: /settings/passkeys — the desktop entry of the passkey screen; the screen itself is PasskeyManager, shared with /m/settings/passkeys

import PasskeyManager from '@/components/settings/PasskeyManager';

export default function PasskeysPage() {
  return (
    <div className="max-w-xl space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-text-primary">Passkey</h1>
        <p className="text-sm text-text-secondary">
          Вход по Face ID или Touch ID вместо ключа. Ключ добавляется на том устройстве, с которого
          потом входят.
        </p>
      </div>
      <PasskeyManager />
    </div>
  );
}
