// Settings: notification status, the approved city with "request another city" (R22), logout.
import { useNavigation, type NavigationProp } from '@react-navigation/native';
import { StyleSheet, Text, View } from 'react-native';

import { Button, colors, Screen, Title } from '../../components/ui';
import { useCities } from '../../components/useCities';
import { he } from '../../i18n/he';
import type { RootStackParams } from '../../navigation/types';
import { useNotificationStore } from '../../notifications';
import { isAdmin, useAuthStore } from '../../state/auth';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
  );
}

export function SettingsScreen() {
  const navigation = useNavigation<NavigationProp<RootStackParams>>();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const permission = useNotificationStore((s) => s.permission);
  const tokenRegistered = useNotificationStore((s) => s.tokenRegistered);
  const { cities } = useCities();
  const admin = isAdmin(user);

  const cityName = cities?.find((c) => c.id === user?.approved_city_id)?.name ?? '—';
  const notificationsText =
    permission !== 'granted'
      ? he.settings.notificationsOff
      : tokenRegistered
        ? he.settings.notificationsOn
        : he.settings.tokenNotRegistered;

  return (
    <Screen>
      <Title>{he.settings.title}</Title>
      <Row label={he.settings.notifications} value={notificationsText} />
      <Row label={he.settings.city} value={admin ? he.settings.adminAllCities : cityName} />
      {admin ? null : (
        <Button variant="link" title={he.settings.requestCity} onPress={() => navigation.navigate('CityChange')} />
      )}
      <Button title={he.settings.logout} onPress={() => void logout()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  label: { fontSize: 16, color: colors.muted },
  value: { fontSize: 16, color: colors.text, fontWeight: '600' },
});
