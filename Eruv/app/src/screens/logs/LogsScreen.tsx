// Logs tab (R23): the city's transitions, results and faults, newest first. Opens on
// status transitions from the last 7 days; filter by event type and date range; pages
// over the server cursor as the list scrolls.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';

import { api, type LogItem, type LogType } from '../../api/client';
import { CitySwitcher } from '../../components/CitySwitcher';
import { EventIcon } from '../../components/EventIcon';
import { tintColors, toneColors } from '../../components/tones';
import { Button, Chip, colors, ErrorText, Field, fonts } from '../../components/ui';
import { he } from '../../i18n/he';
import { formatHebrewDate, hebrewDateAt } from '../../lib/hebrewDate';
import { formatClock } from '../../lib/time';
import { useAuthStore } from '../../state/auth';
import { eventStory } from './eventStory';

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

/** "כ״ב תשרי תשפ״ז · 22:17": the Hebrew date (from sunset, the next day) and the time. */
export function logWhen(iso: string): string {
  return `${formatHebrewDate(hebrewDateAt(new Date(iso)))} · ${formatClock(iso)}`;
}

function LogRow({ item }: { item: LogItem }) {
  const story = eventStory(item);
  const color = story.tone === 'neutral' ? colors.text : toneColors[story.tone];
  return (
    <View testID={`log-${item.kind}-${item.id}`} style={[styles.card, story.muted && styles.muted]}>
      <View style={styles.cardBody}>
        <View style={styles.titleRow}>
          <View style={[styles.dot, { backgroundColor: toneColors[story.tone] }]} />
          <Text style={styles.cardTitle}>{story.title}</Text>
        </View>
        {story.main ? (
          <Text style={[styles.mainPill, { backgroundColor: tintColors[story.tone].bg, color }]}>{story.main}</Text>
        ) : null}
        {story.detail ? <Text style={styles.detailPill}>{story.detail}</Text> : null}
        <Text style={styles.when}>{logWhen(item.occurred_at)}</Text>
      </View>
      <View style={styles.divider} />
      <EventIcon name={story.icon} tone={story.tone} />
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
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginHorizontal: 12,
    marginTop: 10,
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  muted: { opacity: 0.5 },
  cardBody: { flex: 1, gap: 6, alignItems: 'flex-start' },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  cardTitle: { fontFamily: fonts.display, fontSize: 19, lineHeight: 25, color: colors.text, textAlign: 'left' },
  mainPill: {
    fontSize: 15,
    fontWeight: '700',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
    overflow: 'hidden',
    textAlign: 'left',
  },
  detailPill: {
    fontSize: 14,
    color: colors.text,
    backgroundColor: colors.background,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
    overflow: 'hidden',
    textAlign: 'left',
  },
  when: { fontSize: 13, color: colors.muted, textAlign: 'left' },
  divider: { width: 1, alignSelf: 'stretch', backgroundColor: colors.border },
  emptyContainer: { flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  center: { alignItems: 'center', gap: 8 },
  empty: { fontSize: 16, color: colors.muted },
  footer: { padding: 16 },
});
