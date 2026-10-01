// City status banner (R16) with the break navigation link and help (R17).
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { BreakMapping, CityStatus } from '../api/client';
import { he } from '../i18n/he';
import { openNavigation } from '../lib/navLinks';
import { formatClock, formatRelative } from '../lib/time';
import { isStale } from '../state/cityStatus';
import { colors } from './ui';

export type BannerTone = 'ok' | 'break' | 'warning' | 'neutral';

export const bannerColors: Record<BannerTone, string> = {
  ok: colors.success,
  break: '#b3261e',
  warning: '#e65100',
  neutral: '#5f6368',
};

export interface BannerModel {
  tone: BannerTone;
  title: string;
  secondary: { tone: BannerTone; text: string } | null;
  lastCheck: string;
  /** Waze/Google target while a located break is (or was last known to be) active. */
  navigate: { lat: number; lon: number; approximate: boolean } | null;
  showBreakHelp: boolean;
}

export function breakTitle(mapping: BreakMapping | null | undefined): string {
  switch (mapping?.kind) {
    case 'between':
      return mapping.pole_a !== null && mapping.pole_b !== null
        ? he.city.breakBetween(mapping.pole_a, mapping.pole_b)
        : he.city.breakUnknown;
    case 'at_cabinet':
      return he.city.breakAtCabinet;
    case 'beyond_ring':
      return he.city.breakBeyondRing;
    default:
      return he.city.breakUnknown;
  }
}

function navTarget(mapping: BreakMapping | null | undefined): BannerModel['navigate'] {
  if (!mapping || mapping.lat === null || mapping.lon === null) return null;
  if (mapping.kind !== 'between' && mapping.kind !== 'at_cabinet' && mapping.kind !== 'beyond_ring') return null;
  return { lat: mapping.lat, lon: mapping.lon, approximate: mapping.kind === 'beyond_ring' };
}

export function bannerModel(status: CityStatus, now: number, serverUnreachable: boolean): BannerModel {
  const broken = status.display_line_state === 'BREAK';
  const device = status.device_health;
  const mapping = status.active_break?.mapping;

  let tone: BannerTone;
  let title: string;
  let secondary: BannerModel['secondary'] = null;
  if (broken) {
    tone = 'break';
    title = breakTitle(mapping);
    // AE7: a break stays primary; an offline device adds an orange line.
    const since = status.device_health_since ? formatClock(status.device_health_since) : '';
    if (device === 'DISCONNECTED') secondary = { tone: 'warning', text: he.city.disconnectedSince(since).trim() };
    if (device === 'FAULT') secondary = { tone: 'warning', text: he.city.faultSince(since).trim() };
  } else if (device === 'DISCONNECTED') {
    tone = 'warning';
    title = he.city.disconnected;
  } else if (device === 'FAULT') {
    tone = 'warning';
    title = he.city.fault;
  } else if (status.display_line_state === 'AWAITING_REFERENCE') {
    tone = 'neutral';
    title = he.city.awaitingReference;
  } else {
    tone = 'ok';
    title = he.city.intact;
  }

  // "No contact" covers a silent server (R16). An offline device already explains an
  // old last check, and the server is still reporting it, so staleness applies only
  // while the device is reported ONLINE (otherwise AE7 would turn orange after 3 min).
  const noContact = serverUnreachable || (device === 'ONLINE' && isStale(status, now));
  if (noContact) {
    secondary = { tone: 'neutral', text: he.city.lastKnown(title) };
    tone = 'warning';
    title = he.city.noContact;
  }

  return {
    tone,
    title,
    secondary,
    lastCheck: status.last_result_at
      ? he.city.lastCheck(formatClock(status.last_result_at), formatRelative(status.last_result_at, now))
      : he.city.noCheckYet,
    navigate: broken ? navTarget(mapping) : null,
    showBreakHelp: broken,
  };
}

export function StatusBanner({
  status,
  now,
  serverUnreachable,
}: {
  status: CityStatus;
  now: number;
  serverUnreachable: boolean;
}) {
  const model = bannerModel(status, now, serverUnreachable);
  const [helpOpen, setHelpOpen] = useState(false);
  const navigate = model.navigate;

  return (
    <View testID="status-banner" accessibilityRole="summary" style={[styles.banner, { backgroundColor: bannerColors[model.tone] }]}>
      <View style={styles.titleRow}>
        <Text testID="banner-title" style={styles.title}>
          {model.title}
        </Text>
        {model.showBreakHelp ? (
          <Pressable
            testID="banner-info"
            accessibilityRole="button"
            accessibilityLabel={he.city.info}
            hitSlop={8}
            onPress={() => setHelpOpen((open) => !open)}
            style={styles.infoButton}
          >
            <Text style={styles.infoText}>i</Text>
          </Pressable>
        ) : null}
      </View>
      {model.secondary ? (
        <View testID="banner-secondary" style={[styles.secondary, { backgroundColor: bannerColors[model.secondary.tone] }]}>
          <Text style={styles.secondaryText}>{model.secondary.text}</Text>
        </View>
      ) : null}
      {helpOpen && model.showBreakHelp ? <Text style={styles.help}>{he.city.secondBreakHelp}</Text> : null}
      <Text testID="banner-last-check" style={styles.meta}>
        {model.lastCheck}
      </Text>
      {navigate ? (
        <Pressable
          testID="banner-navigate"
          accessibilityRole="link"
          onPress={() => void openNavigation(navigate.lat, navigate.lon)}
          style={styles.navButton}
        >
          <Text style={styles.navText}>{navigate.approximate ? he.city.navigateWazeApprox : he.city.navigateWaze}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: { paddingHorizontal: 16, paddingVertical: 12, gap: 6 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1, color: '#fff', fontSize: 20, fontWeight: '700', textAlign: 'left' },
  infoButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
    borderColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  secondary: { borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6, borderWidth: 1, borderColor: 'rgba(255,255,255,0.6)' },
  secondaryText: { color: '#fff', fontSize: 15, fontWeight: '600', textAlign: 'left' },
  help: { color: '#fff', fontSize: 14, lineHeight: 20, textAlign: 'left' },
  meta: { color: '#fff', fontSize: 13, opacity: 0.9, textAlign: 'left' },
  navButton: { alignSelf: 'flex-start', backgroundColor: '#fff', borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  navText: { color: bannerColors.break, fontSize: 15, fontWeight: '700' },
});
