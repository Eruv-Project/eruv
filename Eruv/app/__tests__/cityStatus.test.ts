import type { CityStatus, Pole } from '../src/api/client';
import {
  applyMessage,
  CityStatusController,
  fromSnapshot,
  isStale,
  type CityStatusDeps,
  type LiveMessage,
  type SocketLike,
} from '../src/state/cityStatus';

function status(overrides: Partial<CityStatus> = {}): CityStatus {
  return {
    id: 7,
    name: 'באר שבע',
    line_state: 'OK',
    display_line_state: 'OK',
    device_health: 'ONLINE',
    device_health_since: '2026-09-30T08:00:00Z',
    last_result_at: '2026-09-30T09:00:00Z',
    active_break: null,
    ...overrides,
  };
}

const MAPPING = { kind: 'between', pole_a: 57, pole_b: 58, lat: 31.25, lon: 34.79, geo_distance_m: 12400, offset_from_a_m: 20 };

function lineEvent(overrides: Record<string, unknown> = {}): LiveMessage {
  return {
    type: 'status_changed',
    event_id: 40,
    city_id: 7,
    dimension: 'line',
    from_state: 'SUSPECT_BREAK',
    to_state: 'BREAK',
    display_line_state: 'BREAK',
    occurred_at: '2026-09-30T09:10:00Z',
    replayed: false,
    mapping: MAPPING,
    detail: null,
    ...overrides,
  } as LiveMessage;
}

describe('cityStatus merge', () => {
  it('applies a WebSocket transition over stale REST state', () => {
    const state = applyMessage(fromSnapshot(status()), lineEvent());
    expect(state.status?.line_state).toBe('BREAK');
    expect(state.status?.display_line_state).toBe('BREAK');
    expect(state.status?.active_break).toEqual({
      event_id: 40,
      occurred_at: '2026-09-30T09:10:00Z',
      replayed: false,
      mapping: MAPPING,
    });
  });

  it('ignores an older event arriving after a newer one', () => {
    let state = applyMessage(fromSnapshot(status()), lineEvent());
    // A late OK that happened before the BREAK must not clear it.
    state = applyMessage(
      state,
      lineEvent({ event_id: 39, to_state: 'OK', display_line_state: 'OK', from_state: 'AWAITING_REFERENCE', occurred_at: '2026-09-30T09:05:00Z', mapping: null }),
    );
    expect(state.status?.display_line_state).toBe('BREAK');
    expect(state.status?.active_break?.event_id).toBe(40);
  });

  it('a recovery clears the active break', () => {
    let state = applyMessage(fromSnapshot(status()), lineEvent());
    state = applyMessage(
      state,
      lineEvent({ event_id: 41, from_state: 'BREAK', to_state: 'OK', display_line_state: 'OK', occurred_at: '2026-09-30T09:20:00Z', mapping: null }),
    );
    expect(state.status?.display_line_state).toBe('OK');
    expect(state.status?.active_break).toBeNull();
  });

  it('ignores a device event older than the snapshot device_health_since', () => {
    const snapshot = fromSnapshot(status({ device_health: 'DISCONNECTED', device_health_since: '2026-09-30T09:00:00Z' }));
    const stale = applyMessage(snapshot, {
      ...lineEvent(),
      dimension: 'device',
      from_state: 'DISCONNECTED',
      to_state: 'ONLINE',
      display_line_state: null,
      occurred_at: '2026-09-30T08:59:00Z',
    } as LiveMessage);
    expect(stale.status?.device_health).toBe('DISCONNECTED');

    const fresh = applyMessage(snapshot, {
      ...lineEvent(),
      dimension: 'device',
      from_state: 'DISCONNECTED',
      to_state: 'ONLINE',
      display_line_state: null,
      occurred_at: '2026-09-30T09:30:00Z',
    } as LiveMessage);
    expect(fresh.status?.device_health).toBe('ONLINE');
    expect(fresh.status?.device_health_since).toBe('2026-09-30T09:30:00Z');
    expect(fresh.status?.display_line_state).toBe('OK');
  });

  it('a usable result moves the last check forward; faults and results without an end event do not', () => {
    const base = fromSnapshot(status());
    const msg = (o: Record<string, unknown>) =>
      ({ type: 'result_received', city_id: 7, result_id: 1, kind: 'result', received_at: '2026-09-30T09:01:30Z', backlog: false, end_event_distance_m: 14000, ...o }) as LiveMessage;
    expect(applyMessage(base, msg({})).status?.last_result_at).toBe('2026-09-30T09:01:30Z');
    expect(applyMessage(base, msg({ kind: 'fault', end_event_distance_m: null })).status?.last_result_at).toBe('2026-09-30T09:00:00Z');
    expect(applyMessage(base, msg({ end_event_distance_m: null })).status?.last_result_at).toBe('2026-09-30T09:00:00Z');
    expect(applyMessage(base, msg({ received_at: '2026-09-30T08:59:00Z' })).status?.last_result_at).toBe('2026-09-30T09:00:00Z');
  });

  it('a hello replaces the snapshot', () => {
    const state = applyMessage(fromSnapshot(status()), { type: 'hello', status: status({ device_health: 'FAULT' }) });
    expect(state.status?.device_health).toBe('FAULT');
  });

  it('the last check is stale after 3 minutes', () => {
    const at = Date.parse('2026-09-30T09:00:00Z');
    expect(isStale(status(), at + 180_000)).toBe(false);
    expect(isStale(status(), at + 180_001)).toBe(true);
    expect(isStale(status({ last_result_at: null }), at + 3_600_000)).toBe(false);
  });
});

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  sent: unknown[] = [];
  constructor(readonly url: string) {}
  close() {
    this.closed = true;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  receive(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop(code = 1006) {
    this.onclose?.({ code });
  }
}

const POLES: Pole[] = [
  { number: 1, lat: 31.25, lon: 34.79 },
  { number: 2, lat: 31.26, lon: 34.8 },
];

function harness(timing: Pick<CityStatusDeps, 'pingIntervalMs' | 'idleTimeoutMs'> = {}) {
  const sockets: FakeSocket[] = [];
  let restOk = true;
  const deps: CityStatusDeps = {
    fetchStatus: jest.fn(async () => {
      if (!restOk) throw new TypeError('Network request failed');
      return status();
    }),
    fetchPoles: jest.fn(async () => POLES),
    socketUrl: jest.fn((cityId: number) => `wss://api.test/ws?token=t&city_id=${cityId}`),
    createSocket: (url: string) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      // While the server is down, every connection attempt fails right away.
      if (!restOk) setTimeout(() => s.drop(), 0);
      return s;
    },
    onAuthRejected: jest.fn(async () => undefined),
    ...timing,
  };
  const controller = new CityStatusController(7, deps);
  return {
    deps,
    controller,
    sockets,
    setRest(ok: boolean) {
      restOk = ok;
    },
  };
}

async function flush() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

describe('CityStatusController', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('loads REST status and poles, then follows the socket', async () => {
    const h = harness();
    expect(h.controller.getView().loading).toBe(true);
    h.controller.start();
    await flush();
    expect(h.controller.getView().loading).toBe(false);
    expect(h.controller.getView().poles).toEqual(POLES);
    expect(h.sockets[0].url).toBe('wss://api.test/ws?token=t&city_id=7');

    h.sockets[0].receive({ type: 'hello', status: status() });
    h.sockets[0].receive(lineEvent());
    expect(h.controller.getView().live.status?.display_line_state).toBe('BREAK');
    h.controller.stop();
  });

  it('reconnects with backoff and refetches REST on reconnect', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });
    const restCalls = (h.deps.fetchStatus as jest.Mock).mock.calls.length;

    h.sockets[0].drop();
    jest.advanceTimersByTime(999);
    expect(h.sockets).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(h.sockets).toHaveLength(2);
    expect((h.deps.fetchStatus as jest.Mock).mock.calls.length).toBe(restCalls + 1);

    // Second failure waits twice as long.
    h.sockets[1].drop();
    jest.advanceTimersByTime(1999);
    expect(h.sockets).toHaveLength(2);
    jest.advanceTimersByTime(1);
    expect(h.sockets).toHaveLength(3);
    h.controller.stop();
  });

  it('reports the server unreachable only after 15 s down and a failed REST refetch', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });

    h.setRest(false);
    h.sockets[0].drop();
    await jest.advanceTimersByTimeAsync(14_000);
    expect(h.controller.getView().serverUnreachable).toBe(false);
    await jest.advanceTimersByTimeAsync(2_000);
    expect(h.controller.getView().serverUnreachable).toBe(true);

    // The REST API answers again: contact is back even before the socket is.
    h.setRest(true);
    await jest.advanceTimersByTimeAsync(20_000);
    expect(h.controller.getView().serverUnreachable).toBe(false);
    h.controller.stop();
  });

  it('a socket down for 15 s with REST still answering is not "no contact"', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].drop();
    await jest.advanceTimersByTimeAsync(20_000);
    expect(h.controller.getView().serverUnreachable).toBe(false);
    h.controller.stop();
  });

  it('a 4401 close runs the auth check before reconnecting', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].drop(4401);
    await flush();
    expect(h.deps.onAuthRejected).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(1_000);
    expect(h.sockets).toHaveLength(2);
    h.controller.stop();
  });

  it('a 4403 close stops reconnecting', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].drop(4403);
    await jest.advanceTimersByTimeAsync(60_000);
    expect(h.sockets).toHaveLength(1);
    expect(h.controller.getView().fatal).toBe(true);
    h.controller.stop();
  });

  it('stop closes the socket and cancels reconnects', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.controller.stop();
    expect(h.sockets[0].closed).toBe(true);
    h.sockets[0].drop();
    await jest.advanceTimersByTimeAsync(60_000);
    expect(h.sockets).toHaveLength(1);
  });

  it('pings the server on an interval while the socket is open', async () => {
    const h = harness({ pingIntervalMs: 1_000, idleTimeoutMs: 1_500 });
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });
    jest.advanceTimersByTime(999);
    expect(h.sockets[0].sent).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(h.sockets[0].sent).toEqual([{ type: 'ping' }]);
    h.sockets[0].receive({ type: 'pong' });
    jest.advanceTimersByTime(1_000);
    expect(h.sockets[0].sent).toEqual([{ type: 'ping' }, { type: 'ping' }]);
    h.controller.stop();
  });

  it('closes a silent socket after the idle window and reconnects', async () => {
    const h = harness({ pingIntervalMs: 1_000, idleTimeoutMs: 1_500 });
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });
    jest.advanceTimersByTime(1_499);
    expect(h.sockets[0].closed).toBe(false);
    jest.advanceTimersByTime(1);
    expect(h.sockets[0].closed).toBe(true);
    // The normal reconnect path: backoff, then a new socket and a REST refetch.
    const restCalls = (h.deps.fetchStatus as jest.Mock).mock.calls.length;
    jest.advanceTimersByTime(1_000);
    expect(h.sockets).toHaveLength(2);
    expect((h.deps.fetchStatus as jest.Mock).mock.calls.length).toBe(restCalls + 1);
    // The old socket's timers are gone: it pings no more.
    const sentBefore = h.sockets[0].sent.length;
    jest.advanceTimersByTime(1_000);
    expect(h.sockets[0].sent.length).toBe(sentBefore);
    h.controller.stop();
  });

  it('any message resets the idle window', async () => {
    const h = harness({ pingIntervalMs: 1_000, idleTimeoutMs: 1_500 });
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });
    jest.advanceTimersByTime(1_200);
    h.sockets[0].receive({ type: 'pong' });
    jest.advanceTimersByTime(1_200);
    h.sockets[0].receive(lineEvent());
    jest.advanceTimersByTime(1_499);
    expect(h.sockets[0].closed).toBe(false);
    expect(h.sockets).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(h.sockets[0].closed).toBe(true);
    h.controller.stop();
  });

  it('uses a 25 s ping and a 35 s idle window by default', async () => {
    const h = harness();
    h.controller.start();
    await flush();
    h.sockets[0].receive({ type: 'hello', status: status() });
    jest.advanceTimersByTime(25_000);
    expect(h.sockets[0].sent).toEqual([{ type: 'ping' }]);
    jest.advanceTimersByTime(9_999);
    expect(h.sockets[0].closed).toBe(false);
    jest.advanceTimersByTime(1);
    expect(h.sockets[0].closed).toBe(true);
    h.controller.stop();
  });

  it('stop clears the heartbeat timers', async () => {
    const h = harness({ pingIntervalMs: 1_000, idleTimeoutMs: 1_500 });
    h.controller.start();
    await flush();
    h.controller.stop();
    expect(jest.getTimerCount()).toBe(0);
  });
});
