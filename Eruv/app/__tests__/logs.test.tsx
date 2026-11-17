import { fireEvent, render, screen } from '@testing-library/react-native';

import { he } from '../src/i18n/he';
import { LogsScreen } from '../src/screens/logs/LogsScreen';
import { resetAuthStore, useAuthStore } from '../src/state/auth';
import { installFakeServer, user, type FakeServer } from '../test-utils/server';

let server: FakeServer;
const NOW = Date.parse('2026-09-30T12:00:00Z');
const clock = () => NOW;
const DAY = 24 * 60 * 60 * 1000;

function transition(id: number, overrides: Record<string, unknown> = {}) {
  return {
    kind: 'transition',
    id,
    occurred_at: '2026-09-30T09:15:00Z',
    replayed: false,
    dimension: 'line',
    from_state: 'OK',
    to_state: 'BREAK',
    mapping: { kind: 'between', pole_a: 2, pole_b: 3, lat: 31.25, lon: 34.79, geo_distance_m: 400, offset_from_a_m: 12 },
    detail: null,
    result_id: 11,
    ...overrides,
  };
}

const logCalls = () => server.calls.filter((c) => c.pathname === '/api/cities/7/logs');

beforeEach(() => {
  resetAuthStore();
  server = installFakeServer();
  useAuthStore.setState({ phase: 'signedIn', user: user() as any, accessToken: 'access-1', refreshToken: 'r', activeCityId: 7 });
});

describe('LogsScreen (R23)', () => {
  it('opens on status transitions from the last 7 days, suspect and replayed rows muted', async () => {
    server.on('GET', '/api/cities/7/logs', {
      status: 200,
      body: {
        items: [
          transition(3),
          transition(2, { from_state: 'SUSPECT_BREAK', to_state: 'OK', mapping: null, detail: 'suspect reading not confirmed: end event 1050.2 m' }),
          transition(1, { dimension: 'device', from_state: 'ONLINE', to_state: 'DISCONNECTED', mapping: null, replayed: true }),
        ],
        next_cursor: null,
      },
    });
    await render(<LogsScreen clock={clock} />);

    expect(await screen.findByTestId('log-transition-3')).toBeTruthy();
    const [call] = logCalls();
    expect(call.query.type).toBe('transitions');
    expect(call.query.from).toBe(new Date(NOW - 7 * DAY).toISOString());
    expect(call.query.limit).toBe('50');
    expect(call.query.cursor).toBeUndefined();
    expect(call.headers.Authorization).toBe('Bearer access-1');

    // Plain words, a picture per event, and no raw server text.
    expect(screen.getByText(he.logs.story.breakFound)).toBeTruthy();
    expect(screen.getByText(he.city.breakBetween(2, 3))).toBeTruthy();
    expect(screen.getByText(he.logs.story.fromStart('400'))).toBeTruthy();
    expect(screen.getByTestId('event-icon-route', { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByText(he.logs.story.suspectGone)).toBeTruthy();
    expect(screen.queryByText(/suspect reading/)).toBeNull();
    expect(screen.getByText(he.logs.story.disconnected)).toBeTruthy();
    expect(screen.getByTestId('event-icon-signalOff', { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByText(`${he.logs.story.checkPower} · ${he.logs.story.replayed}`)).toBeTruthy();
    // Hebrew date and Israel time: 09:15Z on 30 Sep 2026 is 12:15 IDT, 19 Tishrei 5787.
    expect(screen.getAllByText('י״ט תשרי תשפ״ז · 12:15').length).toBeGreaterThan(0);

    expect(screen.getByTestId('log-transition-3')).not.toHaveStyle({ opacity: 0.5 });
    expect(screen.getByTestId('log-transition-2')).toHaveStyle({ opacity: 0.5 });
    expect(screen.getByTestId('log-transition-1')).toHaveStyle({ opacity: 0.5 });
  });

  it('loads the next page from next_cursor on scroll, and shows the empty state', async () => {
    server.on('GET', '/api/cities/7/logs', (_b, _h, query) => {
      if (query.type === 'results') return { status: 200, body: { items: [], next_cursor: null } };
      if (query.cursor === 'c2') return { status: 200, body: { items: [transition(1)], next_cursor: null } };
      return { status: 200, body: { items: [transition(5), transition(4)], next_cursor: 'c2' } };
    });
    await render(<LogsScreen clock={clock} />);
    expect(await screen.findByTestId('log-transition-5')).toBeTruthy();

    await fireEvent(screen.getByTestId('logs-list'), 'onEndReached');
    expect(await screen.findByTestId('log-transition-1')).toBeTruthy();
    expect(logCalls()[1].query.cursor).toBe('c2');
    expect(logCalls()[1].query.type).toBe('transitions');
    expect(screen.getByTestId('log-transition-5')).toBeTruthy();

    // No more pages: another end-reached does not request again.
    await fireEvent(screen.getByTestId('logs-list'), 'onEndReached');
    expect(logCalls()).toHaveLength(2);

    await fireEvent.press(screen.getByTestId('log-type-results'));
    expect(await screen.findByText(he.logs.empty)).toBeTruthy();
    expect(logCalls()[2].query.type).toBe('results');
    expect(logCalls()[2].query.cursor).toBeUndefined();
  });

  it('renders results and faults, and filters by a date range', async () => {
    server.on('GET', '/api/cities/7/logs', (_b, _h, query) => {
      if (query.type === 'faults') {
        return {
          status: 200,
          body: {
            items: [
              { kind: 'fault', id: 8, occurred_at: '2026-09-30T09:00:00Z', replayed: false, seq: 40, measured_at: '2026-09-30T09:00:00Z', fault_kind: 'otdr_timeout', fault_detail: 'no reply', fault_status_code: 3 },
            ],
            next_cursor: null,
          },
        };
      }
      return {
        status: 200,
        body: {
          items: [
            { kind: 'result', id: 9, occurred_at: '2026-09-30T09:00:00Z', replayed: false, seq: 41, measured_at: '2026-09-30T09:00:00Z', end_event_distance_m: 5120.5, fiber_length_m: 5121, link_loss_db: 2.4 },
          ],
          next_cursor: null,
        },
      };
    });
    await render(<LogsScreen clock={clock} />);
    await fireEvent.press(screen.getByTestId('log-type-results'));
    expect(await screen.findByText(he.logs.story.result(41))).toBeTruthy();
    expect(screen.getByText(he.logs.story.measured('5,120.5'))).toBeTruthy();

    await fireEvent.press(screen.getByTestId('log-type-faults'));
    expect(await screen.findByText(he.logs.story.faultTimeout)).toBeTruthy();
    expect(screen.getByText(he.logs.story.fault)).toBeTruthy();

    await fireEvent.press(screen.getByTestId('log-range-month'));
    await screen.findByText(he.logs.story.faultTimeout);
    const monthCall = logCalls()[logCalls().length - 1];
    expect(monthCall.query.from).toBe(new Date(NOW - 30 * DAY).toISOString());
    expect(monthCall.query.type).toBe('faults');

    await fireEvent.press(screen.getByTestId('log-range-custom'));
    await fireEvent.changeText(screen.getByTestId('log-from'), '2026-09-01');
    await fireEvent.changeText(screen.getByTestId('log-to'), '2026-09-10');
    await fireEvent.press(screen.getByTestId('log-apply-range'));
    await screen.findByText(he.logs.story.faultTimeout);
    const custom = logCalls()[logCalls().length - 1];
    expect(custom.query.from).toBe(new Date(2026, 8, 1).toISOString());
    expect(custom.query.to).toBe(new Date(2026, 8, 11).toISOString());
  });
});

describe('eventStory', () => {
  const { eventStory } = require('../src/screens/logs/eventStory');
  const cabinet = (geo: number) =>
    eventStory(transition(9, { from_state: 'BREAK', mapping: { kind: 'at_cabinet', pole_a: 1, pole_b: null, lat: 31.2, lon: 34.7, geo_distance_m: geo, offset_from_a_m: 0 } }));

  it('places a break a little past the launch box at the cabinet, saying why', () => {
    expect(cabinet(0.58)).toMatchObject({ icon: 'cabinet', title: he.logs.story.breakMoved, main: he.city.breakAtCabinet, detail: he.logs.story.nearCabinet('0.6') });
    expect(cabinet(-120)).toMatchObject({ icon: 'cabinet', detail: he.logs.story.atStart });
  });
});
