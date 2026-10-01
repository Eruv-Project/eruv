// Logs tab (R23): the city's transitions, results and faults, newest first. Opens on
// status transitions from the last 7 days; filter by event type and date range; pages
// over the server cursor as the list scrolls.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';

import { api, type LogItem, type LogType } from '../../api/client';
import { CitySwitcher } from '../../components/CitySwitcher';
import { bannerColors, breakTitle } from '../../components/StatusBanner';
import { Button, Chip, colors, ErrorText, Field } from '../../components/ui';
import { he } from '../../i18n/he';
import { formatNumber } from '../../lib/format';
import { formatDateTime } from '../../lib/time';
import { useAuthStore } from '../../state/auth';

const DAY_MS = 24 * 60 * 60 * 1000;
const PAGE_SIZE = 50;
const TYPES: LogType[] = ['transitions', 'results', 'faults'];
type RangeKey = 'day' | 'week' | 'month' | 'custom';
const PRESET_DAYS: Record<Exclude<RangeKey, 'custom'>, number> = { day: 1, week: 7, month: 30 };
const RANGE_KEYS: RangeKey[] = ['day', 'week', 'month', 'custom'];

interface Range {
  key: RangeKey;
  from: string;
  to: string | null;
}

function presetRange(key: Exclude<RangeKey, 'custom'>, now: number): Range {
  return { key, from: new Date(now - PRESET_DAYS[key] * DAY_MS).toISOString(), to: null };
}

/** "YYYY-MM-DD" as the start of that day on the phone's clock, or null. */
function parseDay(text: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim());
  if (!m) return null;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return date.getMonth() === Number(m[2]) - 1 ? date : null;
}

/** Custom range: from the start of the first day to the end of the last day. */
function customRange(fromText: string, toText: string): Range | null {
  const from = parseDay(fromText);
  const to = parseDay(toText);
  if (!from || !to || to < from) return null;
  const end = new Date(to.getFullYear(), to.getMonth(), to.getDate() + 1);
  return { key: 'custom', from: from.toISOString(), to: end.toISOString() };
}

const stateLabel = (state: string) => he.logs.states[state] ?? state;

/** Suspect readings and backlog replays are context, not alerts: shown muted. */
function isMuted(item: LogItem): boolean {
  if (item.replayed) return true;
  return item.kind === 'transition' && (item.from_state === 'SUSPECT_BREAK' || item.to_state === 'SUSPECT_BREAK');
}

function describe(item: LogItem): { title: string; lines: string[]; color: string } {
  switch (item.kind) {
    case 'transition': {
      const lines: string[] = [];
      if (item.to_state === 'BREAK') lines.push(breakTitle(item.mapping));
      if (item.detail) {
        lines.push(item.detail === 'suspect reading not confirmed' ? he.logs.suspectNotConfirmed : item.detail);
      }
      const color =
        item.to_state === 'BREAK'
          ? bannerColors.break
          : item.to_state === 'DISCONNECTED' || item.to_state === 'FAULT'
            ? bannerColors.warning
            : item.to_state === 'OK' || item.to_state === 'ONLINE'
              ? bannerColors.ok
              : bannerColors.neutral;
      return {
        title: he.logs.transition(he.logs.dimension[item.dimension], stateLabel(item.from_state), stateLabel(item.to_state)),
        lines,
        color,
      };
    }
    case 'result': {
      const parts = [
        item.end_event_distance_m !== null ? he.logs.endEvent(formatNumber(item.end_event_distance_m)) : he.logs.noEndEvent,
      ];
      if (item.fiber_length_m !== null) parts.push(he.logs.fiberLength(formatNumber(item.fiber_length_m)));
      if (item.link_loss_db !== null) parts.push(he.logs.linkLoss(formatNumber(item.link_loss_db)));
      return { title: he.logs.result(item.seq), lines: [parts.join(' · ')], color: bannerColors.neutral };
    }
    case 'fault': {
      const detail = [item.fault_detail, item.fault_status_code !== null ? he.logs.faultCode(item.fault_status_code) : null]
        .filter(Boolean)
        .join(' · ');
      return { title: he.logs.fault(item.fault_kind), lines: detail ? [detail] : [], color: bannerColors.warning };
    }
  }
}

function LogRow({ item }: { item: LogItem }) {
  const { title, lines, color } = describe(item);
  const muted = isMuted(item);
  return (
    <View testID={`log-${item.kind}-${item.id}`} style={[styles.row, muted && styles.muted]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <View style={styles.rowBody}>
        <Text style={styles.rowTitle}>{title}</Text>
        {lines.map((line) => (
          <Text key={line} style={styles.rowLine}>
            {line}
          </Text>
        ))}
        {item.replayed ? <Text style={styles.rowLine}>{he.logs.replayed}</Text> : null}
        <Text style={styles.rowTime}>{formatDateTime(item.occurred_at)}</Text>
      </View>
    </View>
  );
}

export function LogsScreen({ clock = Date.now }: { clock?: () => number }) {
  const cityId = useAuthStore((s) => s.activeCityId);
  const [type, setType] = useState<LogType>('transitions');
  const [range, setRange] = useState<Range>(() => presetRange('week', clock()));
  const [customOpen, setCustomOpen] = useState(false);
  const [fromText, setFromText] = useState('');
  const [toText, setToText] = useState('');
  const [rangeError, setRangeError] = useState(false);

  const [items, setItems] = useState<LogItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  // Each new filter bumps the generation, so a late page of an old filter is dropped.
  const generation = useRef(0);
  const pageInFlight = useRef(false);

  const loadFirst = useCallback(async () => {
    if (cityId === null) return;
    const gen = ++generation.current;
    pageInFlight.current = false;
    setLoading(true);
    setError(false);
    setItems([]);
    setNextCursor(null);
    try {
      const page = await api.cityLogs(cityId, { type, from: range.from, to: range.to, limit: PAGE_SIZE });
      if (gen !== generation.current) return;
      setItems(page.items);
      setNextCursor(page.next_cursor);
    } catch {
      if (gen === generation.current) setError(true);
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }, [cityId, type, range]);

  useEffect(() => {
    void loadFirst();
  }, [loadFirst]);

  const loadMore = useCallback(async () => {
    if (cityId === null || !nextCursor || loading || pageInFlight.current) return;
    const gen = generation.current;
    pageInFlight.current = true;
    setLoadingMore(true);
    try {
      const page = await api.cityLogs(cityId, {
        type,
        from: range.from,
        to: range.to,
        limit: PAGE_SIZE,
        cursor: nextCursor,
      });
      if (gen !== generation.current) return;
      setItems((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch {
      if (gen === generation.current) setError(true);
    } finally {
      if (gen === generation.current) {
        pageInFlight.current = false;
        setLoadingMore(false);
      }
    }
  }, [cityId, nextCursor, loading, type, range]);

  function selectRange(key: RangeKey) {
    if (key === 'custom') {
      setCustomOpen(true);
      return;
    }
    setCustomOpen(false);
    setRangeError(false);
    setRange(presetRange(key, clock()));
  }

  function applyCustom() {
    const next = customRange(fromText, toText);
    setRangeError(!next);
    if (next) setRange(next);
  }

  return (
    <View style={styles.container}>
      <CitySwitcher />
      <View style={styles.filters}>
        <View style={styles.chipRow}>
          {TYPES.map((t) => (
            <Chip key={t} testID={`log-type-${t}`} label={he.logs.types[t]} active={type === t} onPress={() => setType(t)} />
          ))}
        </View>
        <View style={styles.chipRow}>
          {RANGE_KEYS.map((key) => (
            <Chip
              key={key}
              testID={`log-range-${key}`}
              label={he.logs.ranges[key]}
              active={key === 'custom' ? customOpen || range.key === 'custom' : !customOpen && range.key === key}
              onPress={() => selectRange(key)}
            />
          ))}
        </View>
        {customOpen ? (
          <View style={styles.custom}>
            <Field testID="log-from" placeholder={he.logs.fromDate} value={fromText} onChangeText={setFromText} />
            <Field testID="log-to" placeholder={he.logs.toDate} value={toText} onChangeText={setToText} />
            <ErrorText>{rangeError ? he.logs.invalidRange : null}</ErrorText>
            <Button testID="log-apply-range" title={he.logs.applyRange} onPress={applyCustom} />
          </View>
        ) : null}
      </View>
      <FlatList
        testID="logs-list"
        data={items}
        keyExtractor={(item) => `${item.kind}-${item.id}`}
        renderItem={({ item }) => <LogRow item={item} />}
        onEndReached={() => void loadMore()}
        onEndReachedThreshold={0.5}
        contentContainerStyle={items.length ? undefined : styles.emptyContainer}
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator testID="logs-loading" />
          ) : error ? (
            <View style={styles.center}>
              <ErrorText>{he.logs.loadError}</ErrorText>
              <Button variant="link" title={he.common.retry} onPress={() => void loadFirst()} />
            </View>
          ) : (
            <Text style={styles.empty}>{he.logs.empty}</Text>
          )
        }
        ListFooterComponent={
          loadingMore ? (
            <ActivityIndicator style={styles.footer} />
          ) : error && items.length ? (
            <Button variant="link" title={he.common.retry} onPress={() => void loadMore()} />
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  filters: { padding: 8, gap: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  custom: { gap: 8 },
  row: {
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  muted: { opacity: 0.5 },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 6 },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { fontSize: 16, fontWeight: '600', color: colors.text, textAlign: 'left' },
  rowLine: { fontSize: 14, color: colors.text, textAlign: 'left' },
  rowTime: { fontSize: 13, color: colors.muted, textAlign: 'left' },
  emptyContainer: { flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  center: { alignItems: 'center', gap: 8 },
  empty: { fontSize: 16, color: colors.muted },
  footer: { padding: 16 },
});
