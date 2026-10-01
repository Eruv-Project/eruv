// A tiny fake of the Eruv server for app tests: route table over a mocked global fetch.
// A route registered without a query string also answers requests that carry one;
// the parsed query is recorded on the call and passed to the handler.
export type Reply = { status: number; body?: unknown };
export type Handler = (body: any, headers: Record<string, string>, query: Record<string, string>) => Reply | Promise<Reply>;

export interface FakeCall {
  method: string;
  path: string;
  pathname: string;
  query: Record<string, string>;
  /** Parsed JSON, or the raw body (e.g. FormData) when it is not a string. */
  body: any;
  headers: Record<string, string>;
}

export interface FakeServer {
  routes: Record<string, Handler>;
  calls: FakeCall[];
  on(method: string, path: string, handler: Handler | Reply): void;
}

function parseQuery(qs: string | undefined): Record<string, string> {
  const query: Record<string, string> = {};
  for (const part of (qs ?? '').split('&')) {
    if (!part) continue;
    const [k, v = ''] = part.split('=');
    query[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return query;
}

export function installFakeServer(base = 'https://api.test'): FakeServer {
  const server: FakeServer = {
    routes: {},
    calls: [],
    on(method, path, handler) {
      this.routes[`${method} ${path}`] = typeof handler === 'function' ? handler : () => handler;
    },
  };
  (globalThis as any).fetch = jest.fn(async (url: string, init: any = {}) => {
    const method = init.method ?? 'GET';
    const path = url.replace(base, '');
    const [pathname, qs] = path.split('?');
    const query = parseQuery(qs);
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    const headers = init.headers ?? {};
    server.calls.push({ method, path, pathname, query, body, headers });
    const handler = server.routes[`${method} ${path}`] ?? server.routes[`${method} ${pathname}`];
    const reply = handler ? await handler(body, headers, query) : { status: 404, body: { detail: 'Not Found' } };
    const text = reply.body === undefined ? '' : JSON.stringify(reply.body);
    return { status: reply.status, ok: reply.status >= 200 && reply.status < 300, text: async () => text };
  });
  return server;
}

export const CITIES = [
  { id: 7, name: 'באר שבע' },
  { id: 9, name: 'ירושלים' },
];

export function user(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'דוד',
    phone: '050-0000000',
    email: 'david@example.com',
    role: 'maintainer',
    approval_state: 'approved',
    approved_city_id: 7,
    requested_city_id: null,
    ...overrides,
  };
}

export function tokens(overrides: Record<string, unknown> = {}) {
  return { access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', user: user(overrides) };
}

export function cityStatus(id: number) {
  const city = CITIES.find((c) => c.id === id)!;
  return {
    id,
    name: city.name,
    line_state: 'OK',
    display_line_state: 'OK',
    device_health: 'ONLINE',
    device_health_since: null,
    last_result_at: null,
    active_break: null,
  };
}

export function poles() {
  return [
    { number: 1, lat: 31.25, lon: 34.79 },
    { number: 2, lat: 31.252, lon: 34.792 },
    { number: 3, lat: 31.249, lon: 34.794 },
  ];
}

export function adminCity(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    name: 'באר שבע',
    launch_offset_m: 30,
    break_tolerance_m: 20,
    reference_fiber_length_m: null,
    reference_set_at: null,
    line_state: 'AWAITING_REFERENCE',
    device_health: 'ONLINE',
    has_device: false,
    device_key_rotated_at: null,
    pole_count: 3,
    perimeter_m: 1234.5,
    ...overrides,
  };
}

export function adminUser(overrides: Record<string, unknown> = {}) {
  return { ...user({ id: 20, name: 'משה', email: 'moshe@example.com', ...overrides }), created_at: '2026-09-29T08:00:00Z' };
}
