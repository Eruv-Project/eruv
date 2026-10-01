// Waiting for admin approval (R20): polls every 30 s and on "check again".
import { useEffect, useState } from 'react';

import { Body, Button, Screen, Title } from '../../components/ui';
import { he } from '../../i18n/he';
import { useAuthStore } from '../../state/auth';

export const PENDING_POLL_MS = 30_000;

export function PendingScreen() {
  const hasToken = useAuthStore((s) => s.registrationToken !== null);
  const checkRegistration = useAuthStore((s) => s.checkRegistration);
  const goToLogin = useAuthStore((s) => s.goToLogin);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!hasToken) return;
    void checkRegistration();
    const timer = setInterval(() => void checkRegistration(), PENDING_POLL_MS);
    return () => clearInterval(timer);
  }, [hasToken, checkRegistration]);

  async function checkNow() {
    setBusy(true);
    await checkRegistration();
    setBusy(false);
  }

  return (
    <Screen>
      <Title>{he.pending.title}</Title>
      <Body>{he.pending.body}</Body>
      {hasToken ? (
        <Button title={he.pending.checkAgain} onPress={() => void checkNow()} busy={busy} />
      ) : (
        <>
          {/* Logged in on a device that never registered: no token to poll with. */}
          <Body>{he.pending.noToken}</Body>
          <Button title={he.pending.toLogin} onPress={() => goToLogin()} />
        </>
      )}
    </Screen>
  );
}
