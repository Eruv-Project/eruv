// Live city status (R16, R17): the REST snapshot merged with WebSocket updates.
//
// The controller keeps one socket per city, reconnects with exponential backoff
// and refetches REST (status + poles) at every reconnect attempt. It reports the
// server unreachable once the socket has been down for more than 15 s and a REST
// refetch fails. While a socket is up it pings on an interval and, when no
// message arrives within the idle window, closes it and reconnects (see
// PING_INTERVAL_MS, IDLE_TIMEOUT_MS). Staleness of the last check (> 3 min) is
// a pure function of the status and the clock (`isStale`), so the screen
// re-evaluates it as time passes.
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';

import {
  api,
  liveUpdatesUrl,
  type ActiveBreak,
  type BreakMapping,
  type CityStatus,
  type DeviceHealth,
  type LineState,
  type Pole,
} from '../api/client';

export const CADENCE_MS = 60_000;
/** Three cadence periods (R16). */
export const STALE_AFTER_MS = 3 * CADENCE_MS;
/** How long the socket may be down before a failing REST refetch means "no contact". */
export const SOCKET_GRACE_MS = 15_000;
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
/** Refusals that retrying cannot fix: city not allowed, no city, unknown city. */
const FATAL_CLOSE_CODES = [4400, 4403, 4404];
const UNAUTHORIZED_CLOSE_CODE = 4401;
/** Client ping cadence on an open socket; the server answers with a pong. */
export const PING_INTERVAL_MS = 25_000;
/** No message at all for this long means a dead (half-open) socket: close and reconnect. */
export const IDLE_TIMEOUT_MS = PING_INTERVAL_MS + 10_000;

export type LiveMessage =
  | { type: 'hello'; status: CityStatus }
  | {
      type: 'status_changed';
      event_id: number;
      city_id: number;
      dimension: 'line' | 'device';
      from_state: string;
      to_state: string;
      display_line_state: CityStatus['display_line_state'] | null;
      occurred_at: string;
      replayed: boolean;
      mapping: BreakMapping | null;
      detail: string | null;
    }
  | {
      type: 'result_received';
      city_id: number;
      result_id: number;
      kind: 'result' | 'fault';
      received_at: string;
      backlog: boolean;
      end_event_distance_m: number | null;
    }
  | { type: 'pong' };

/** Ordering key of the newest applied change in one dimension. */
interface Mark {
  at: number;
  id: number;
}

export interface LiveState {
  status: CityStatus | null;
  line: Mark | null;
  device: Mark | null;
}

const EMPTY: LiveState = { status: null, line: null, device: null };

function mark(iso: string, id: number): Mark {
  return { at: Date.parse(iso), id };
}

function newer(a: Mark | null, b: Mark | null): Mark | null {
  if (!a) return b;
  if (!b) return a;
  return a.at > b.at || (a.at === b.at && a.id >= b.id) ? a : b;
}

function isOlder(m: Mark, than: Mark | null): boolean {
  return than !== null && (m.at < than.at || (m.at === than.at && m.id < than.id));
}

function laterIso(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return Date.parse(b) > Date.parse(a) ? b : a;
}

/** Merge a full snapshot (REST or hello). A dimension already moved past the
 *  snapshot by a newer WebSocket event keeps the newer value. */
export function mergeSnapshot(state: LiveState, snap: CityStatus): LiveState {
  // Line transitions happen when a result is processed, stamped with the same
  // time as last_result_at, so the last check bounds the snapshot's line state.
  const snapLine = newer(
    snap.active_break ? mark(snap.active_break.occurred_at, snap.active_break.event_id) : null,
    snap.last_result_at ? mark(snap.last_result_at, 0) : null,
  );
  const snapDevice = snap.device_health_since ? mark(snap.device_health_since, 0) : null;
  const prev = state.status;
  const keepLine = prev !== null && prev.id === snap.id && state.line !== null && snapLine !== null && isOlder(snapLine, state.line);
  const keepDevice =
    prev !== null && prev.id === snap.id && state.device !== null && snapDevice !== null && isOlder(snapDevice, state.device);
  const status: CityStatus = {
    ...snap,
    last_result_at: prev?.id === snap.id ? laterIso(prev.last_result_at, snap.last_result_at) : snap.last_result_at,
  };
  if (keepLine && prev) {
    status.line_state = prev.line_state;
    status.display_line_state = prev.display_line_state;
    status.active_break = prev.active_break;
  }
  if (keepDevice && prev) {
    status.device_health = prev.device_health;
    status.device_health_since = prev.device_health_since;
  }
  return {
    status,
    line: keepLine ? state.line : snapLine,
    device: keepDevice ? state.device : snapDevice,
  };
}

export function fromSnapshot(snap: CityStatus): LiveState {
  return mergeSnapshot(EMPTY, snap);
}

function displayOf(line: LineState): CityStatus['display_line_state'] {
  return line === 'SUSPECT_BREAK' ? 'OK' : line;
}

/** Apply one WebSocket message. Events older than what is already shown are ignored. */
export function applyMessage(state: LiveState, msg: LiveMessage): LiveState {
  if (msg.type === 'hello') return mergeSnapshot(state, msg.status);
  const status = state.status;
  if (!status) return state;

  if (msg.type === 'status_changed') {
    if (msg.city_id !== status.id) return state;
    const m = mark(msg.occurred_at, msg.event_id);
    if (msg.dimension === 'line') {
      if (isOlder(m, state.line)) return state;
      const line = msg.to_state as LineState;
      const active_break: ActiveBreak | null =
        line === 'BREAK'
          ? { event_id: msg.event_id, occurred_at: msg.occurred_at, replayed: msg.replayed, mapping: msg.mapping }
          : null;
      return {
        ...state,
        line: m,
        status: { ...status, line_state: line, display_line_state: msg.display_line_state ?? displayOf(line), active_break },
      };
    }
    if (isOlder(m, state.device)) return state;
    return {
      ...state,
      device: m,
      status: { ...status, device_health: msg.to_state as DeviceHealth, device_health_since: msg.occurred_at },
    };
  }

  if (msg.type === 'result_received') {
    // Mirrors the server: only a result with an end event counts as a completed check.
    if (msg.city_id !== status.id || msg.kind !== 'result' || msg.end_event_distance_m === null) return state;
    const last = laterIso(status.last_result_at, msg.received_at);
    return last === status.last_result_at ? state : { ...state, status: { ...status, last_result_at: last } };
  }
  return state;
}

/** The last completed check is older than 3 cadence periods (R16). */
export function isStale(status: CityStatus, now: number): boolean {
  return status.last_result_at !== null && now - Date.parse(status.last_result_at) > STALE_AFTER_MS;
}

export interface SocketLike {
  onopen: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export interface CityStatusDeps {
  fetchStatus(cityId: number): Promise<CityStatus>;
  fetchPoles(cityId: number): Promise<Pole[]>;
  socketUrl(cityId: number): string | null;
  createSocket(url: string): SocketLike;
  /** After a 4401 close: refresh the session, or end it and route (auth store). */
  onAuthRejected(): Promise<void>;
  /** Liveness timings; tests shorten them. Defaults: PING_INTERVAL_MS / IDLE_TIMEOUT_MS. */
  pingIntervalMs?: number;
  idleTimeoutMs?: number;
}

export const defaultCityStatusDeps: CityStatusDeps = {
  fetchStatus: (cityId) => api.cityStatus(cityId),
  fetchPoles: (cityId) => api.cityPoles(cityId),
  socketUrl: liveUpdatesUrl,
  createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
  // /me goes through the authed client: a 401 refreshes once, a failed refresh or a
  // 403 not_approved ends the session and the navigator routes (R20).
  onAuthRejected: async () => {
    await api.me();
  },
};

export interface CityView {
  live: LiveState;
  poles: Pole[] | null;
  /** No REST answer yet (first load skeleton). */
  loading: boolean;
  restFailed: boolean;
  /** Socket down for more than SOCKET_GRACE_MS. */
  socketDownLong: boolean;
  /** R16 "No contact with monitoring server" from connectivity. */
  serverUnreachable: boolean;
  /** The server refused this city for good (4400/4403/4404). */
  fatal: boolean;
}

const INITIAL_VIEW: CityView = {
  live: EMPTY,
  poles: null,
  loading: true,
  restFailed: false,
  socketDownLong: false,
  serverUnreachable: false,
  fatal: false,
};

export class CityStatusController {
  private view: CityView = INITIAL_VIEW;
  private listeners = new Set<() => void>();
  private socket: SocketLike | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private graceTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private down = false;
  private stopped = true;

  constructor(
    readonly cityId: number,
    private readonly deps: CityStatusDeps = defaultCityStatusDeps,
  ) {}

  getView = (): CityView => this.view;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.refresh();
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.detachSocket();
  }

  /** Forget the current socket and close it without running its onclose path. */
  private detachSocket(): void {
    this.clearHeartbeat();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.onmessage = null;
      socket.close();
    }
  }

  /** Refetch status and poles over REST. */
  refresh = async (): Promise<void> => {
    const [status, poles] = await Promise.allSettled([
      this.deps.fetchStatus(this.cityId),
      this.deps.fetchPoles(this.cityId),
    ]);
    if (this.stopped) return;
    this.patch({
      live: status.status === 'fulfilled' ? mergeSnapshot(this.view.live, status.value) : this.view.live,
      poles: poles.status === 'fulfilled' ? poles.value : this.view.poles,
      restFailed: status.status === 'rejected',
      loading: false,
    });
  };

  private patch(changes: Partial<CityView>): void {
    const next = { ...this.view, ...changes };
    next.serverUnreachable = next.socketDownLong && next.restFailed;
    this.view = next;
    this.listeners.forEach((l) => l());
  }

  private connect(): void {
    if (this.stopped) return;
    const url = this.deps.socketUrl(this.cityId);
    if (!url) {
      this.onDown();
      this.scheduleRetry();
      return;
    }
    const socket = this.deps.createSocket(url);
    this.socket = socket;
    socket.onerror = () => undefined; // onclose follows
    this.startHeartbeat(socket);
    socket.onmessage = (ev) => {
      if (this.socket !== socket) return;
      this.resetIdle();
      let msg: LiveMessage;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'hello') this.onUp();
      const live = applyMessage(this.view.live, msg);
      if (live !== this.view.live) this.patch({ live });
    };
    socket.onclose = (ev) => {
      if (this.socket !== socket) return;
      this.clearHeartbeat();
      this.socket = null;
      this.onClosed(ev?.code);
    };
  }

  /** Ping on an interval and treat a silent socket as dead, so a half-open
   *  connection does not hide live transitions until the stale rule kicks in. */
  private startHeartbeat(socket: SocketLike): void {
    this.clearHeartbeat();
    this.pingTimer = setInterval(() => {
      if (this.socket !== socket) return;
      try {
        socket.send(JSON.stringify({ type: 'ping' }));
      } catch {
        // Not open yet or already closing: the idle timer decides.
      }
    }, this.deps.pingIntervalMs ?? PING_INTERVAL_MS);
    this.resetIdle();
  }

  private resetIdle(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.stopped || !this.socket) return;
      this.detachSocket();
      this.onClosed(undefined);
    }, this.deps.idleTimeoutMs ?? IDLE_TIMEOUT_MS);
  }

  private clearHeartbeat(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.pingTimer = null;
    this.idleTimer = null;
  }

  private onClosed(code: number | undefined): void {
    if (this.stopped) return;
    if (code !== undefined && FATAL_CLOSE_CODES.includes(code)) {
      this.clearTimers();
      this.patch({ fatal: true });
      return;
    }
    this.onDown();
    if (code === UNAUTHORIZED_CLOSE_CODE) {
      void this.deps
        .onAuthRejected()
        .catch(() => undefined)
        .finally(() => this.scheduleRetry());
    } else {
      this.scheduleRetry();
    }
  }

  private onUp(): void {
    this.attempt = 0;
    this.down = false;
    if (this.graceTimer) clearTimeout(this.graceTimer);
    this.graceTimer = null;
    this.patch({ socketDownLong: false, fatal: false });
  }

  private onDown(): void {
    if (this.down) return;
    this.down = true;
    this.graceTimer = setTimeout(() => {
      this.graceTimer = null;
      if (this.stopped) return;
      this.patch({ socketDownLong: true });
      void this.refresh();
    }, SOCKET_GRACE_MS);
  }

  private scheduleRetry(): void {
    if (this.stopped || this.retryTimer) return;
    const delay = Math.min(BACKOFF_BASE_MS * 2 ** this.attempt, BACKOFF_MAX_MS);
    this.attempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.stopped) return;
      void this.refresh();
      this.connect();
    }, delay);
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.graceTimer) clearTimeout(this.graceTimer);
    this.retryTimer = null;
    this.graceTimer = null;
    this.clearHeartbeat();
  }
}

const noSubscribe = () => () => undefined;
const initialView = () => INITIAL_VIEW;
const CLOCK_TICK_MS = 15_000;

/** Live status for the active city, plus a clock for staleness and relative times. */
export function useCityStatus(
  cityId: number | null,
  deps: CityStatusDeps = defaultCityStatusDeps,
  clock: () => number = Date.now,
) {
  const controller = useMemo(() => (cityId === null ? null : new CityStatusController(cityId, deps)), [cityId, deps]);
  useEffect(() => {
    controller?.start();
    return () => controller?.stop();
  }, [controller]);
  const view = useSyncExternalStore(controller?.subscribe ?? noSubscribe, controller?.getView ?? initialView);

  const [now, setNow] = useState(clock);
  useEffect(() => {
    const timer = setInterval(() => setNow(clock()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, [clock]);
  // A new update may carry a timestamp later than the last tick.
  useEffect(() => setNow(clock()), [view, clock]);

  return { view, now, refresh: controller?.refresh ?? (async () => undefined) };
}
