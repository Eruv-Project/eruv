// City tab (R15–R17): status banner over the OpenStreetMap ring, live over WebSocket.
// The shell pieces (notification warning strip, admin city switcher) stay on top.
import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { CityStatus, Pole } from '../../api/client';
import { CitySwitcher } from '../../components/CitySwitcher';
import { EruvMap, type MapBreakPoint } from '../../components/EruvMap';
import { NotificationWarningStrip } from '../../components/NotificationWarningStrip';
import { StatusBanner } from '../../components/StatusBanner';
import { colors } from '../../components/ui';
import { he } from '../../i18n/he';
import { useAuthStore } from '../../state/auth';
import { useCityStatus } from '../../state/cityStatus';

/** Stable empty list so the map's memoization holds before poles load. */
const NO_POLES: Pole[] = [];

/** The X and bounding poles for the map while the city shows a located break. */
export function mapBreakPoint(status: CityStatus | null): MapBreakPoint | null {
  const mapping = status?.display_line_state === 'BREAK' ? status.active_break?.mapping : null;
  if (!mapping || mapping.lat === null || mapping.lon === null) return null;
  const poles = [mapping.pole_a, mapping.pole_b].filter((n): n is number => n !== null);
  return { lat: mapping.lat, lon: mapping.lon, poles };
}

export function CityScreen() {
  const cityId = useAuthStore((s) => s.activeCityId);
  const { view, now, refresh } = useCityStatus(cityId);
  const status = view.live.status;
  const breakPoint = useMemo(() => mapBreakPoint(status), [status]);

  let body;
  if (cityId === null) {
    body = <Text style={styles.centerText}>{he.city.noCity}</Text>;
  } else if (view.fatal) {
    body = <Text style={styles.centerText}>{he.city.unavailable}</Text>;
  } else if (status) {
    body = (
      <>
        <View style={styles.header}>
          <Text testID="city-name" style={styles.name}>
            {status.name}
          </Text>
          <Pressable testID="city-refresh" accessibilityRole="button" hitSlop={8} onPress={() => void refresh()}>
            <Text style={styles.link}>{he.city.refresh}</Text>
          </Pressable>
        </View>
        <StatusBanner status={status} now={now} serverUnreachable={view.serverUnreachable} />
        <EruvMap poles={view.poles ?? NO_POLES} breakPoint={breakPoint} />
      </>
    );
  } else if (view.loading) {
    body = (
      <View testID="city-loading" style={styles.skeleton}>
        <View style={[styles.bone, { width: '40%', height: 22 }]} />
        <View style={[styles.bone, { height: 72 }]} />
        <View style={[styles.bone, { flex: 1 }]} />
      </View>
    );
  } else {
    body = (
      <View style={styles.center}>
        <Text style={styles.error}>{he.city.loadError}</Text>
        <Pressable testID="city-refresh" accessibilityRole="button" onPress={() => void refresh()}>
          <Text style={styles.link}>{he.common.retry}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <NotificationWarningStrip />
      <CitySwitcher />
      {body}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  name: { fontSize: 20, fontWeight: '700', color: colors.text },
  link: { color: colors.primary, fontSize: 15 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  centerText: { flex: 1, textAlign: 'center', textAlignVertical: 'center', fontSize: 18, color: colors.text, padding: 24 },
  error: { color: colors.danger, fontSize: 16 },
  skeleton: { flex: 1, padding: 16, gap: 12 },
  bone: { backgroundColor: '#e4e7eb', borderRadius: 8 },
});
