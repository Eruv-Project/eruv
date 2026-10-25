// City tab (R15–R17): status banner over the OpenStreetMap ring, live over WebSocket.
// The shell pieces (notification warning strip, admin city switcher) stay on top.
import { Ionicons } from '@expo/vector-icons';
import { NavigationContext } from '@react-navigation/native';
import { useContext, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { CityStatus, Pole } from '../../api/client';
import { CitySwitcher } from '../../components/CitySwitcher';
import { EruvMap, type MapBreakPoint } from '../../components/EruvMap';
import { NotificationWarningStrip } from '../../components/NotificationWarningStrip';
import { StatusBanner } from '../../components/StatusBanner';
import { colors, fonts } from '../../components/ui';
import { he } from '../../i18n/he';
import { useMyLocation } from '../../lib/useMyLocation';
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

/** True while this screen is the visible tab; true outside a navigator (tests). */
function useTabFocused(): boolean {
  const navigation = useContext(NavigationContext);
  const [focused, setFocused] = useState(() => navigation?.isFocused() ?? true);
  useEffect(() => {
    if (!navigation) return;
    const offFocus = navigation.addListener('focus', () => setFocused(true));
    const offBlur = navigation.addListener('blur', () => setFocused(false));
    return () => {
      offFocus();
      offBlur();
    };
  }, [navigation]);
  return focused;
}

export function CityScreen() {
  const cityId = useAuthStore((s) => s.activeCityId);
  const { view, now, refresh } = useCityStatus(cityId);
  const status = view.live.status;
  const breakPoint = useMemo(() => mapBreakPoint(status), [status]);
  // The phone's position on the map, only while this tab is on screen.
  const { location: me } = useMyLocation(useTabFocused());

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
          <Pressable
            testID="city-refresh"
            accessibilityRole="button"
            accessibilityLabel={he.city.refresh}
            hitSlop={10}
            onPress={() => void refresh()}
            style={({ pressed }) => [styles.refresh, pressed && { opacity: 0.6 }]}
          >
            <Ionicons name="refresh" size={22} color={colors.primary} />
          </Pressable>
        </View>
        <StatusBanner status={status} now={now} serverUnreachable={view.serverUnreachable} />
        <EruvMap poles={view.poles ?? NO_POLES} breakPoint={breakPoint} closed={status.ring_closed !== false} me={me} />
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
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 6,
  },
  name: { flex: 1, fontFamily: fonts.display, fontSize: 24, lineHeight: 32, color: colors.gold, textAlign: 'left' },
  refresh: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  link: { color: colors.primary, fontSize: 15, fontWeight: '600' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  centerText: { flex: 1, textAlign: 'center', textAlignVertical: 'center', fontSize: 18, color: colors.text, padding: 24 },
  error: { color: colors.danger, fontSize: 16 },
  skeleton: { flex: 1, padding: 16, gap: 12 },
  bone: { backgroundColor: colors.surface, borderRadius: 10 },
});
