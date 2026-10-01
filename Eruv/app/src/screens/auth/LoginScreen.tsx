import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useState } from 'react';

import { Body, Button, ErrorText, Field, Screen, Title } from '../../components/ui';
import { he } from '../../i18n/he';
import type { RootStackParams } from '../../navigation/types';
import { useAuthStore } from '../../state/auth';
import { authErrorMessage } from './errors';

export function LoginScreen({ navigation }: NativeStackScreenProps<RootStackParams, 'Login'>) {
  const login = useAuthStore((s) => s.login);
  const notice = useAuthStore((s) => s.loginNotice);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!email.trim() || !password) {
      setError(he.login.missingFields);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(authErrorMessage(err, { 401: he.login.invalidCredentials }));
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Title>{he.login.title}</Title>
      {notice === 'approved' ? <Body>{he.pending.approved}</Body> : null}
      <Field
        testID="login-email"
        placeholder={he.login.email}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
      />
      <Field
        testID="login-password"
        placeholder={he.login.password}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="current-password"
      />
      <ErrorText>{error}</ErrorText>
      <Button testID="login-submit" title={he.login.submit} onPress={() => void submit()} busy={busy} />
      <Button variant="link" title={he.login.toRegister} onPress={() => navigation.navigate('Register')} />
    </Screen>
  );
}
