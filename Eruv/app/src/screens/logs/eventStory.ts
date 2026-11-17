// Each log item told in plain words for the log's cards: a picture, a title, the main
// sentence and an optional detail. The server's English `detail` strings are matched
// here and never shown as they are.
import type { BreakMapping, LogItem } from '../../api/client';
import type { EventIconName } from '../../components/EventIcon';
import { breakTitle } from '../../components/StatusBanner';
import type { BannerTone } from '../../components/tones';
import { he } from '../../i18n/he';
import { formatNumber } from '../../lib/format';

export interface EventStory {
  icon: EventIconName;
  tone: BannerTone;
  title: string;
  main: string | null;
  detail: string | null;
  /** Suspect readings and late (replayed) items: context, shown faded. */
  muted: boolean;
}

const s = he.logs.story;

const firstNumber = (text: string | null) => {
  const m = text ? /(-?\d+(?:\.\d+)?)\s*m\b/.exec(text) : null;
  return m ? Number(m[1]) : null;
};

function breakIcon(mapping: BreakMapping | null): EventIconName {
  if (mapping?.kind === 'between') return 'route';
  if (mapping?.kind === 'at_cabinet') return 'cabinet';
  return 'brokenRing';
}

function breakPlace(mapping: BreakMapping | null): { main: string | null; detail: string | null } {
  const main = mapping && mapping.kind !== 'unknown' ? breakTitle(mapping) : null;
  const distance = mapping?.geo_distance_m ?? null;
  if (mapping?.kind === 'at_cabinet') {
    return { main, detail: distance !== null && distance > 0 ? s.nearCabinet(formatNumber(distance)) : s.atStart };
  }
  return { main, detail: distance !== null && distance > 0 ? s.fromStart(formatNumber(distance)) : null };
}

function faultSentence(text: string | null): string | null {
  if (!text) return null;
  if (text.startsWith('no valid test result')) return s.faultNoResults;
  if (text.startsWith('otdr_timeout')) return s.faultTimeout;
  if (text.startsWith('otdr_socket') || text.startsWith('otdr_unreachable')) return s.faultNoLink;
  if (text.startsWith('equipment fault')) return s.faultReported;
  return null;
}

function transitionStory(item: Extract<LogItem, { kind: 'transition' }>): Omit<EventStory, 'muted'> {
  const { from_state: from, to_state: to, detail, mapping } = item;
  if (item.dimension === 'line') {
    if (to === 'BREAK') {
      return { icon: breakIcon(mapping), tone: 'break', title: from === 'BREAK' ? s.breakMoved : s.breakFound, ...breakPlace(mapping) };
    }
    if (to === 'SUSPECT_BREAK') return { icon: 'search', tone: 'neutral', title: s.suspect, main: s.checkingAgain, detail: null };
    if (to === 'OK' && from === 'SUSPECT_BREAK') return { icon: 'search', tone: 'neutral', title: s.suspectGone, main: s.intact, detail: null };
    if (to === 'OK' && from === 'AWAITING_REFERENCE') {
      const length = firstNumber(detail);
      return { icon: 'ruler', tone: 'ok', title: s.referenceSet, main: length !== null ? s.fiberLength(formatNumber(length)) : null, detail: null };
    }
    if (to === 'OK') {
      const longer = detail?.includes('re-baseline') ?? false;
      return { icon: 'intact', tone: 'ok', title: s.repaired, main: s.intactAgain, detail: longer ? s.longerThanReference : null };
    }
  } else {
    if (to === 'DISCONNECTED') return { icon: 'signalOff', tone: 'warning', title: s.disconnected, main: s.noSignal, detail: s.checkPower };
    if (to === 'FAULT') return { icon: 'tool', tone: 'warning', title: s.fault, main: faultSentence(detail), detail: null };
    if (to === 'ONLINE' && from === 'FAULT') return { icon: 'tool', tone: 'ok', title: s.faultCleared, main: s.validResult, detail: null };
    if (to === 'ONLINE') return { icon: 'signalOn', tone: 'ok', title: s.reconnected, main: s.backOnline, detail: null };
  }
  return { icon: 'chart', tone: 'neutral', title: s.changed, main: null, detail: null };
}

export function eventStory(item: LogItem): EventStory {
  let story: Omit<EventStory, 'muted'>;
  let muted = item.replayed;
  switch (item.kind) {
    case 'transition':
      story = transitionStory(item);
      muted ||= item.from_state === 'SUSPECT_BREAK' && item.to_state !== 'BREAK';
      muted ||= item.to_state === 'SUSPECT_BREAK';
      break;
    case 'result':
      story = {
        icon: 'chart',
        tone: 'neutral',
        title: s.result(item.seq),
        main: item.end_event_distance_m !== null ? s.measured(formatNumber(item.end_event_distance_m)) : s.noEnd,
        detail: item.link_loss_db !== null ? s.loss(formatNumber(item.link_loss_db)) : null,
      };
      break;
    case 'fault':
      story = { icon: 'tool', tone: 'warning', title: s.fault, main: faultSentence(item.fault_kind), detail: null };
      break;
  }
  if (item.replayed) story = { ...story, detail: story.detail ? `${story.detail} · ${s.replayed}` : s.replayed };
  return { ...story, muted };
}
