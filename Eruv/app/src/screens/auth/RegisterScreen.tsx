import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useState } from 'react';

import { Body, Button, ErrorText, Field, Screen, Title } from '../../components/ui';
import { he } from '../../i18n/he';
import type { RootStackParams } from '../../navigation/types';
import { useAuthStore } from '../../state/auth';
import { CityPicker } from './CityPickerScreen';
import { authErrorMessage } from './errors';

export function RegisterScreen({ navigation }: NativeStackScreenProps<RootStackParams, 'Register'>) {
  const register = useAuthStore((s) => s.register);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [cityId, setCityId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim() || !phone.trim() || !email.trim() || !password || cityId === null) {
      setError(he.register.missingFields);
      return;
    }
    if (password.length < 8) {
      setError(he.register.passwordTooShort);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register({ name: name.trim(), phone: phone.trim(), email: email.trim(), password, city_id: cityId });
    } catch (err) {
      setError(
        authErrorMessage(err, {
          409: he.register.emailTaken,
          404: he.register.cityNotFound,
          422: he.register.missingFields,
        }),
      );
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Title>{he.register.title}</Title>
      <Field testID="register-name" placeholder={he.register.name} value={name} onChangeText={setName} autoComplete="name" />
      <Field
        testID="register-phone"
        placeholder={he.register.phone}
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        autoComplete="tel"
      />
      <Field
        testID="register-email"
        placeholder={he.register.email}
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        autoComplete="email"
      />
      <Field
        testID="register-password"
        placeholder={he.register.password}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="new-password"
      />
      <Body>{he.register.city}</Body>
      <CityPicker selectedId={cityId} onSelect={setCityId} />
      <ErrorText>{error}</ErrorText>
      <Button testID="register-submit" title={he.register.submit} onPress={() => void submit()} busy={busy} />
      <Button variant="link" title={he.register.toLogin} onPress={() => navigation.navigate('Login')} />
    </Screen>
  );
}
