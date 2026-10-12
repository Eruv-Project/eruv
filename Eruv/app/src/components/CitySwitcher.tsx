// Admin-only city switcher at the top of the City and Logs tabs. Renders nothing for maintainers.
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';

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
    // A wrapping row, not a horizontal ScrollView: in RTL, Android opens a horizontal
    // ScrollView scrolled past its content, so the chips were off screen.
    <View testID="city-switcher" style={styles.bar}>
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
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    padding: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
});
