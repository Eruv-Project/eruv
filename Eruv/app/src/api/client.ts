// HTTP client for the Eruv server (U4 auth API; U6 push tokens and logs; U9 admin API).
import { apiBaseUrl } from '../config';

export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'disabled';
export type Role = 'maintainer' | 'admin';

export interface User {
  id: number;
  name: string;
  phone: string;
  email: string;
  role: Role;
  approval_state: ApprovalState;
  approved_city_id: number | null;
  requested_city_id: number | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface CityName {
  id: number;
  name: string;
}

export type LineState = 'AWAITING_REFERENCE' | 'OK' | 'SUSPECT_BREAK' | 'BREAK';
export type DeviceHealth = 'ONLINE' | 'DISCONNECTED' | 'FAULT';

/** Where the server placed a break on the pole ring (server app/mapping.py). */
export interface BreakMapping {
  kind: 'between' | 'at_cabinet' | 'beyond_ring' | 'unknown';
  pole_a: number | null;
  pole_b: number | null;
  lat: number | null;
  lon: number | null;
  geo_distance_m: number | null;
  offset_from_a_m: number | null;
}

export interface ActiveBreak {
  event_id: number;
  occurred_at: string;
  replayed: boolean;
  mapping: BreakMapping | null;
}

/** GET /api/cities/{id}/status and the WebSocket hello (server CityStatusOut). */
export interface CityStatus {
  id: number;
  name: string;
  line_state: LineState;
  /** What the banner shows: SUSPECT_BREAK arrives as OK. */
  display_line_state: Exclude<LineState, 'SUSPECT_BREAK'>;
  device_health: DeviceHealth;
  device_health_since: string | null;
  /** Server receive time of the last valid test result ("last check"). */
  last_result_at: string | null;
  active_break: ActiveBreak | null;
}

export interface Pole {
  number: number;
  lat: number;
  lon: number;
}

export interface RegisterInput {
  name: string;
  phone: string;
  email: string;
  password: string;
  city_id: number;
}

export interface RegisterResult {
  user_id: number;
  approval_state: ApprovalState;
  registration_token: string;
}

export interface CityChangeResult {
  approval_state: ApprovalState;
  requested_city_id: number;
  registration_token: string;
}

// ---- Logs (GET /api/cities/{id}/logs, R23) ----

export type LogType = 'transitions' | 'results' | 'faults';

interface LogBase {
  id: number;
  occurred_at: string;
  replayed: boolean;
}

export interface TransitionLog extends LogBase {
  kind: 'transition';
  dimension: 'line' | 'device';
  from_state: string;
  to_state: string;
  mapping: BreakMapping | null;
  detail: string | null;
  result_id: number | null;
}

export interface ResultLog extends LogBase {
  kind: 'result';
  seq: number;
  measured_at: string | null;
  end_event_distance_m: number | null;
  fiber_length_m: number | null;
  link_loss_db: number | null;
}

export interface FaultLog extends LogBase {
  kind: 'fault';
  seq: number;
  measured_at: string | null;
  fault_kind: string;
  fault_detail: string | null;
  fault_status_code: number | null;
}

export type LogItem = TransitionLog | ResultLog | FaultLog;

export interface LogPage {
  items: LogItem[];
  next_cursor: string | null;
}

export interface LogQuery {
  type: LogType;
  from?: string | null;
  to?: string | null;
  limit?: number;
  cursor?: string | null;
}

// ---- Admin (R24–R27) ----

export interface AdminUser extends User {
  created_at: string;
}

export type UserAction = 'approve' | 'reject' | 'disable' | 'promote';

export interface AdminCity {
  id: number;
  name: string;
  launch_offset_m: number;
  break_tolerance_m: number;
  reference_fiber_length_m: number | null;
  reference_set_at: string | null;
  line_state: LineState;
  device_health: DeviceHealth;
  has_device: boolean;
  device_key_rotated_at: string | null;
  pole_count: number;
  perimeter_m: number | null;
}

export interface CityInput {
  name: string;
  launch_offset_m?: number;
  break_tolerance_m?: number;
}

export interface DeviceKey {
  device_id: number;
  city_id: number;
  api_key: string;
}

export interface PolePreview {
  poles: Pole[];
  count: number;
  perimeter_m: number;
}

/** One entry of a 422 `{"detail":{"code":"invalid_poles","errors":[...]}}`. */
export interface PoleImportError {
  row: number | null;
  message: string;
  missing_number: number | null;
}

export interface ReferenceResult {
  reference_fiber_length_m: number;
  reference_set_at: string;
  line_state: LineState;
}

/** A picked file for a multipart upload (React Native FormData file part). */
export interface UploadFile {
  uri: string;
  name: string;
  mimeType?: string | null;
}

/** `detail.code` of an API error, when the server sent one. */
export function errorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = err.detail as { code?: unknown } | null;
  return typeof detail?.code === 'string' ? detail.code : null;
}

function queryString(params: Record<string, string | number | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`API error ${status}`);
  }
}

/** The approval state carried by a 403 `{"detail":{"code":"not_approved",...}}`, else null. */
export function notApprovedState(err: unknown): ApprovalState | null {
  if (!(err instanceof ApiError) || err.status !== 403) return null;
  const detail = err.detail as { code?: string; approval_state?: ApprovalState } | null;
  return detail?.code === 'not_approved' && detail.approval_state ? detail.approval_state : null;
}

export type SessionEndReason = 'expired' | 'pending' | 'rejected' | 'disabled';

/** How the client reaches the auth store without importing it (avoids an import cycle). */
export interface SessionBridge {
  accessToken(): string | null;
  refreshToken(): string | null;
  onRefreshed(pair: TokenPair): Promise<void>;
  onSessionEnded(reason: SessionEndReason): void;
}

let bridge: SessionBridge | null = null;
export function bindSession(b: SessionBridge): void {
  bridge = b;
}

/** A request with no answer by then is abandoned, so a hung connection reads as a network error (R16). */
export const REQUEST_TIMEOUT_MS = 10_000;

async function send(path: string, init: { method?: string; body?: unknown; token?: string | null }): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  // A FormData body (multipart upload) sets its own Content-Type with the boundary.
  const multipart = typeof FormData !== 'undefined' && init.body instanceof FormData;
  if (init.body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
  if (init.token) headers.Authorization = `Bearer ${init.token}`;
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Rejects before aborting, so it wins the race even against a fetch that ignores its signal.
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new TypeError('Network request timed out'));
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      fetch(`${apiBaseUrl()}${path}`, {
        method: init.method ?? 'GET',
        headers,
        body: init.body === undefined ? undefined : multipart ? (init.body as FormData) : JSON.stringify(init.body),
        signal: controller.signal,
      }),
      timeout,
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

async function publicRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return parse<T>(await send(path, { method, body }));
}

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time; resolves true when a new pair was stored. */
function refreshOnce(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const token = bridge?.refreshToken();
      if (!token) return false;
      try {
        const pair = await publicRequest<TokenPair>('/api/auth/refresh', 'POST', { refresh_token: token });
        await bridge?.onRefreshed(pair);
        return true;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return false;
        throw err; // network trouble: keep the session, surface the error
      }
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

/** Bearer request. A 401 triggers one refresh and retry; a failed refresh or a
 *  403 not_approved ends the session so the navigator routes to the right screen (R20). */
async function authedRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  try {
    let res = await send(path, { method, body, token: bridge?.accessToken() });
    if (res.status === 401) {
      if (!(await refreshOnce())) {
        bridge?.onSessionEnded('expired');
        return await parse<T>(res);
      }
      res = await send(path, { method, body, token: bridge?.accessToken() });
      if (res.status === 401) bridge?.onSessionEnded('expired');
    }
    return await parse<T>(res);
  } catch (err) {
    const state = notApprovedState(err);
    if (state && state !== 'approved') bridge?.onSessionEnded(state);
    throw err;
  }
}

export const api = {
  cities: () => publicRequest<CityName[]>('/api/cities'),
  register: (input: RegisterInput) => publicRequest<RegisterResult>('/api/auth/register', 'POST', input),
  login: (email: string, password: string) =>
    publicRequest<TokenPair>('/api/auth/login', 'POST', { email, password }),
  registrationStatus: (registration_token: string) =>
    publicRequest<{ approval_state: ApprovalState }>('/api/auth/registration-status', 'POST', {
      registration_token,
    }),
  me: () => authedRequest<User>('/api/auth/me'),
  cityChange: (city_id: number) => authedRequest<CityChangeResult>('/api/auth/city-change', 'POST', { city_id }),
  cityStatus: (cityId: number) => authedRequest<CityStatus>(`/api/cities/${cityId}/status`),
  cityPoles: (cityId: number) => authedRequest<Pole[]>(`/api/cities/${cityId}/poles`),
  registerPushToken: (token: string, platform: string) =>
    authedRequest<unknown>('/api/push-tokens', 'POST', { token, platform }),
  unregisterPushToken: (token: string) => authedRequest<unknown>('/api/push-tokens', 'DELETE', { token }),
  cityLogs: (cityId: number, q: LogQuery) =>
    authedRequest<LogPage>(
      `/api/cities/${cityId}/logs${queryString({ type: q.type, from: q.from, to: q.to, limit: q.limit, cursor: q.cursor })}`,
    ),

  adminUsers: (approval_state: ApprovalState) =>
    authedRequest<AdminUser[]>(`/api/admin/users${queryString({ approval_state })}`),
  adminUserAction: (userId: number, action: UserAction) =>
    authedRequest<AdminUser>(`/api/admin/users/${userId}/${action}`, 'POST'),
  adminCities: () => authedRequest<AdminCity[]>('/api/admin/cities'),
  adminCreateCity: (input: CityInput) => authedRequest<AdminCity>('/api/admin/cities', 'POST', input),
  adminUpdateCity: (cityId: number, patch: { launch_offset_m?: number; break_tolerance_m?: number }) =>
    authedRequest<AdminCity>(`/api/admin/cities/${cityId}`, 'PATCH', patch),
  adminDeviceKey: (cityId: number) => authedRequest<DeviceKey>(`/api/admin/cities/${cityId}/device-key`, 'POST'),
  adminPreviewPoles: (cityId: number, file: UploadFile) => {
    const form = new FormData();
    // React Native's FormData takes a {uri, name, type} object as a file part.
    form.append('file', { uri: file.uri, name: file.name, type: file.mimeType ?? 'application/octet-stream' } as any);
    return authedRequest<PolePreview>(`/api/admin/cities/${cityId}/poles/preview`, 'POST', form);
  },
  adminReplacePoles: (cityId: number, poles: Pole[]) =>
    authedRequest<{ count: number; perimeter_m: number }>(`/api/admin/cities/${cityId}/poles`, 'PUT', { poles }),
  adminSetReference: (cityId: number, confirm_short: boolean) =>
    authedRequest<ReferenceResult>(`/api/admin/cities/${cityId}/reference`, 'POST', { confirm_short }),
};

/** Live-status socket URL for a city (server app/ws.py), or null without a session. */
export function liveUpdatesUrl(cityId: number): string | null {
  const token = bridge?.accessToken();
  if (!token) return null;
  const base = apiBaseUrl().replace(/^http/, 'ws');
  return `${base}/ws?token=${encodeURIComponent(token)}&city_id=${cityId}`;
}
