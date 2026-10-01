// Rejected and disabled users: no access, contact the admin (R20).
import { Body, Button, Screen, Title } from '../../components/ui';
import { he } from '../../i18n/he';
import { useAuthStore } from '../../state/auth';

function Blocked({ title, body }: { title: string; body: string }) {
  const logout = useAuthStore((s) => s.logout);
  return (
    <Screen>
      <Title>{title}</Title>
      <Body>{body}</Body>
      <Button variant="link" title={he.backToLogin} onPress={() => void logout()} />
    </Screen>
  );
}

export function RejectedScreen() {
  return <Blocked title={he.rejected.title} body={he.rejected.body} />;
}

export function DisabledScreen() {
  return <Blocked title={he.disabled.title} body={he.disabled.body} />;
}
