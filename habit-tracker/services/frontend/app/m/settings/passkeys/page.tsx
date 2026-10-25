'use client';
// [review:need-review] 205
// summary: /m/settings/passkeys — the mobile passkey screen, reached from the «Passkey» row of /m/more

import PasskeyManager from '@/components/settings/PasskeyManager';

export default function MobilePasskeysPage() {
  return (
    <div className="space-y-4">
      <p className="text-sm text-text-secondary">
        Добавьте passkey этого телефона — и входите по Face ID, без ключа.
      </p>
      <PasskeyManager />
    </div>
  );
}
