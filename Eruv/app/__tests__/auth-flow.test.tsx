import { act, fireEvent, render, screen } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';

import App from '../App';
import { he } from '../src/i18n/he';
import { resetNotificationStore } from '../src/notifications';
import { resetAuthStore, STORAGE_KEYS } from '../src/state/auth';
import { CITIES, cityStatus, installFakeServer, tokens, user, type FakeServer } from '../test-utils/server';

const secure = SecureStore as unknown as { __store: Map<string, string> };
let server: FakeServer;

beforeEach(() => {
  secure.__store.clear();
  resetAuthStore();
  resetNotificationStore();
  server = installFakeServer();
  server.on('GET', '/api/cities', { status: 200, body: CITIES });
  server.on('GET', '/api/cities/7/status', { status: 200, body: cityStatus(7) });
  server.on('GET', '/api/cities/9/status', { status: 200, body: cityStatus(9) });
  server.on('POST', '/api/push-tokens', { status: 201, body: {} });
});

afterEach(() => {
  jest.useRealTimers();
});

async function logIn(email = 'david@example.com', password = 'password1') {
  await fireEvent.changeText(await screen.findByTestId('login-email'), email);
  await fireEvent.changeText(screen.getByTestId('login-password'), password);
  await fireEvent.press(screen.getByTestId('login-submit'));
}

async function startSignedIn(overrides: Record<string, unknown> = {}) {
  secure.__store.set(STORAGE_KEYS.access, 'access-1');
  secure.__store.set(STORAGE_KEYS.refresh, 'refresh-1');
  server.on('GET', '/api/auth/me', { status: 200, body: user(overrides) });
  await render(<App />);
  await screen.findByText(he.city.intact);
}

describe('approval gate', () => {
  it('shows the pending screen after a pending user logs in and offers no city screen', async () => {
    server.on('POST', '/api/auth/login', {
      status: 403,
      body: { detail: { code: 'not_approved', approval_state: 'pending' } },
    });
    await render(<App />);
    await logIn();

    expect(await screen.findByText(he.pending.title)).toBeTruthy();
    expect(screen.queryByText(he.tabs.city)).toBeNull();
    expect(screen.queryByText(he.city.intact)).toBeNull();
    expect(server.calls.some((c) => c.path.startsWith('/api/cities/'))).toBe(false);
  });

  it('moves from pending to login when the 30 s status poll reports approval', async () => {
    jest.useFakeTimers();
    secure.__store.set(STORAGE_KEYS.registration, 'reg-token');
    let state = 'pending';
    server.on('POST', '/api/auth/registration-status', (body) =>
      body.registration_token === 'reg-token'
        ? { status: 200, body: { approval_state: state } }
        : { status: 404, body: { detail: 'unknown registration' } },
    );
    await render(<App />);
    expect(await screen.findByText(he.pending.title)).toBeTruthy();
    const checksBefore = server.calls.filter((c) => c.path === '/api/auth/registration-status').length;

    state = 'approved';
    await act(async () => {
      jest.advanceTimersByTime(30_000);
    });

    expect(await screen.findByTestId('login-submit')).toBeTruthy();
    expect(screen.getByText(he.pending.approved)).toBeTruthy();
    expect(server.calls.filter((c) => c.path === '/api/auth/registration-status').length).toBe(checksBefore + 1);
    expect(secure.__store.has(STORAGE_KEYS.registration)).toBe(false);
  });

  it('checks at once when "check again" is pressed', async () => {
    secure.__store.set(STORAGE_KEYS.registration, 'reg-token');
    let state = 'pending';
    server.on('POST', '/api/auth/registration-status', () => ({ status: 200, body: { approval_state: state } }));
    await render(<App />);
    await screen.findByText(he.pending.title);

    state = 'approved';
    await fireEvent.press(screen.getByText(he.pending.checkAgain));
    expect(await screen.findByTestId('login-submit')).toBeTruthy();
  });

  it('routes an approved user to their approved city', async () => {
    server.on('POST', '/api/auth/login', { status: 200, body: tokens({ approved_city_id: 7 }) });
    await render(<App />);
    await logIn();

    expect(await screen.findByText('באר שבע')).toBeTruthy();
    expect(screen.getByText(he.city.intact)).toBeTruthy();
    const statusCall = server.calls.find((c) => c.path === '/api/cities/7/status');
    expect(statusCall?.headers.Authorization).toBe('Bearer access-1');
    expect(secure.__store.get(STORAGE_KEYS.refresh)).toBe('refresh-1');
    // Maintainers get no admin tab and no city switcher.
    expect(screen.queryByText(he.tabs.admin)).toBeNull();
    expect(screen.queryByTestId('city-switcher')).toBeNull();
  });

  it('gives admins the admin tab and a city switcher', async () => {
    await startSignedIn({ role: 'admin', approved_city_id: null });
    expect(screen.getByText(he.tabs.admin)).toBeTruthy();
    await fireEvent.press(await screen.findByTestId('city-switcher-9'));
    expect(await screen.findByTestId('city-name')).toHaveTextContent('ירושלים');
  });
});

describe('session loss (R20)', () => {
  it('logs out to the login screen when the refresh is rejected with 401', async () => {
    secure.__store.set(STORAGE_KEYS.access, 'expired');
    secure.__store.set(STORAGE_KEYS.refresh, 'revoked');
    server.on('GET', '/api/auth/me', { status: 401, body: { detail: 'invalid token' } });
    server.on('POST', '/api/auth/refresh', { status: 401, body: { detail: 'access revoked' } });
    await render(<App />);

    expect(await screen.findByTestId('login-submit')).toBeTruthy();
    expect(server.calls.filter((c) => c.path === '/api/auth/refresh')).toHaveLength(1);
    expect(secure.__store.has(STORAGE_KEYS.access)).toBe(false);
    expect(secure.__store.has(STORAGE_KEYS.refresh)).toBe(false);
  });

  it('refreshes once on a 401 and retries the request', async () => {
    secure.__store.set(STORAGE_KEYS.access, 'expired');
    secure.__store.set(STORAGE_KEYS.refresh, 'refresh-1');
    server.on('GET', '/api/auth/me', (_b, h) =>
      h.Authorization === 'Bearer access-2' ? { status: 200, body: user() } : { status: 401, body: {} },
    );
    server.on('POST', '/api/auth/refresh', {
      status: 200,
      body: { ...tokens(), access_token: 'access-2', refresh_token: 'refresh-2' },
    });
    await render(<App />);

    expect(await screen.findByText(he.city.intact)).toBeTruthy();
    expect(secure.__store.get(STORAGE_KEYS.refresh)).toBe('refresh-2');
  });

  it('routes a disabled user to the disabled screen at login', async () => {
    server.on('POST', '/api/auth/login', {
      status: 403,
      body: { detail: { code: 'not_approved', approval_state: 'disabled' } },
    });
    await render(<App />);
    await logIn();
    expect(await screen.findByText(he.disabled.title)).toBeTruthy();
    expect(screen.getByText(he.disabled.body)).toBeTruthy();
  });

  it('routes to the disabled screen on a mid-session 403 disabled', async () => {
    await startSignedIn();
    server.on('GET', '/api/cities/7/status', {
      status: 403,
      body: { detail: { code: 'not_approved', approval_state: 'disabled' } },
    });
    await fireEvent.press(screen.getByTestId('city-refresh'));
    expect(await screen.findByText(he.disabled.title)).toBeTruthy();
    expect(screen.queryByText(he.tabs.city)).toBeNull();
    expect(secure.__store.has(STORAGE_KEYS.access)).toBe(false);
  });

  it('routes a rejected user to the rejected screen', async () => {
    server.on('POST', '/api/auth/login', {
      status: 403,
      body: { detail: { code: 'not_approved', approval_state: 'rejected' } },
    });
    await render(<App />);
    await logIn();
    expect(await screen.findByText(he.rejected.title)).toBeTruthy();
  });
});

describe('city choice', () => {
  it('lists the cities from the server when registering, and registration leads to pending', async () => {
    server.on('POST', '/api/auth/register', (body) =>
      body.city_id === 9
        ? { status: 201, body: { user_id: 3, approval_state: 'pending', registration_token: 'reg-new' } }
        : { status: 404, body: { detail: 'city not found' } },
    );
    server.on('POST', '/api/auth/registration-status', { status: 200, body: { approval_state: 'pending' } });
    await render(<App />);
    await fireEvent.press(await screen.findByText(he.login.toRegister));

    expect(await screen.findByText('באר שבע')).toBeTruthy();
    expect(screen.getByText('ירושלים')).toBeTruthy();

    await fireEvent.changeText(screen.getByTestId('register-name'), 'דוד');
    await fireEvent.changeText(screen.getByTestId('register-phone'), '050-1234567');
    await fireEvent.changeText(screen.getByTestId('register-email'), 'david@example.com');
    await fireEvent.changeText(screen.getByTestId('register-password'), 'password1');
    await fireEvent.press(screen.getByText('ירושלים'));
    await fireEvent.press(screen.getByTestId('register-submit'));

    expect(await screen.findByText(he.pending.title)).toBeTruthy();
    expect(secure.__store.get(STORAGE_KEYS.registration)).toBe('reg-new');
    expect(server.calls.find((c) => c.path === '/api/auth/register')?.body).toEqual({
      name: 'דוד',
      phone: '050-1234567',
      email: 'david@example.com',
      password: 'password1',
      city_id: 9,
    });
  });

  it('shows the pending screen after a city change from settings', async () => {
    server.on('POST', '/api/auth/city-change', (body) => ({
      status: 200,
      body: { approval_state: 'pending', requested_city_id: body.city_id, registration_token: 'reg-change' },
    }));
    server.on('POST', '/api/auth/registration-status', { status: 200, body: { approval_state: 'pending' } });
    await startSignedIn();

    await fireEvent.press(screen.getByText(he.tabs.settings));
    await fireEvent.press(await screen.findByText(he.settings.requestCity));
    await fireEvent.press(await screen.findByText('ירושלים'));
    await fireEvent.press(screen.getByText(he.cityPicker.submitChange));

    expect(await screen.findByText(he.pending.title)).toBeTruthy();
    expect(screen.queryByText(he.tabs.city)).toBeNull();
    expect(server.calls.find((c) => c.path === '/api/auth/city-change')?.body).toEqual({ city_id: 9 });
    expect(secure.__store.get(STORAGE_KEYS.registration)).toBe('reg-change');
    expect(secure.__store.has(STORAGE_KEYS.access)).toBe(false);
  });
});
