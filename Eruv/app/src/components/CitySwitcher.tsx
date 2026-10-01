// Admin-only city switcher at the top of the City and Logs tabs. Renders nothing for maintainers.
import { useEffect } from 'react';
import { ScrollView, StyleSheet } from 'react-native';

import { isAdmin, useAuthStore } from '../state/auth';
import { useCities } from './useCities';
import { Chip, colors } from './ui';

export function CitySwitcher() {
  const admin = useAuthStore((s) => isAdmin(s.user));
  if (!admin) return null;
  return <AdminCitySwitcher />;
}

function AdminCitySwitcher() {
  const { cities } = useCities();
  const activeCityId = useAuthStore((s) => s.activeCityId);
  const setActiveCity = useAuthStore((s) => s.setActiveCity);

  // An admin has no approved city of their own: start on the first one.
  useEffect(() => {
    if (activeCityId === null && cities?.length) setActiveCity(cities[0].id);
  }, [activeCityId, cities, setActiveCity]);

  return (
    <ScrollView horizontal testID="city-switcher" contentContainerStyle={styles.row} style={styles.bar}>
      {(cities ?? []).map((city) => {
        const active = city.id === activeCityId;
        return (
          <Chip
            key={city.id}
            testID={`city-switcher-${city.id}`}
            label={city.name}
            active={active}
            onPress={() => setActiveCity(city.id)}
          />
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  bar: { flexGrow: 0, borderBottomWidth: 1, borderBottomColor: colors.border },
  row: { padding: 8, gap: 8 },
});
