// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: /m/more route — renders the MoreSheet list of screens missing from the tab bar
// [review:need-review] 205
// summary: plus the «Passkey» row under it, drawn only while passkey is on

import MoreSheet from '@/components/mobile/MoreSheet';
import PasskeyMoreLink from '@/components/settings/PasskeyMoreLink';

export default function MobileMorePage() {
  return (
    <div className="space-y-3">
      <MoreSheet />
      <PasskeyMoreLink />
    </div>
  );
}
