import { act, fireEvent, screen, within } from '@testing-library/react-native';
import * as Clipboard from 'expo-clipboard';
import { Share } from 'react-native';

import { he } from '../src/i18n/he';
import { resetAuthStore, useAuthStore } from '../src/state/auth';
import { adminNav, renderAdmin, spyAlerts } from '../test-utils/admin';
import { adminCity, adminUser, installFakeServer, type FakeServer, user } from '../test-utils/server';

jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn(async () => true) }));
jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));

let server: FakeServer;
let alerts: ReturnType<typeof spyAlerts>;
const posts = (suffix: string) => server.calls.filter((c) => c.method === 'POST' && c.path.endsWith(suffix));

const PENDING = adminUser({ id: 20, name: 'משה', approval_state: 'pending', approved_city_id: null, requested_city_id: 7 });
const APPROVED = adminUser({ id: 21, name: 'רחל', approval_state: 'approved', approved_city_id: 7 });
const ME = adminUser({ id: 1, name: 'מנהל', role: 'admin', approval_state: 'approved', approved_city_id: null });

beforeEach(() => {
  resetAuthStore();
  alerts = spyAlerts();
  server = installFakeServer();
  useAuthStore.setState({
    phase: 'signedIn',
    user: user({ id: 1, role: 'admin', approved_city_id: null }) as any,
    accessToken: 'access-1',
    refreshToken: 'r',
  });
  server.on('GET', '/api/admin/users', (_b, _h, q) => ({
    status: 200,
    body: q.approval_state === 'pending' ? [PENDING] : q.approval_state === 'approved' ? [APPROVED, ME] : [],
  }));
  server.on('GET', '/api/admin/cities', { status: 200, body: [adminCity()] });
  server.on('GET', '/api/cities', { status: 200, body: [{ id: 7, name: 'באר שבע' }] });
});

afterEach(() => alerts.spy.mockRestore());

describe('Admin users (R24)', () => {
  it.each([
    ['approve', 20, he.admin.users.confirmApprove('משה', 'באר שבע')],
    ['reject', 20, he.admin.users.confirmReject('משה')],
    ['disable', 21, he.admin.users.confirmDisable('רחל')],
    ['promote', 21, he.admin.users.confirmPromote('רחל')],
  ])('%s asks for confirmation before calling the API', async (action, id, message) => {
    server.on('POST', `/api/admin/users/${id}/${action}`, { status: 200, body: {} });
    await renderAdmin();
    await fireEvent.press(await screen.findByTestId(`user-${id}-${action}`));

    expect(alerts.last()?.message).toBe(message);
    expect(posts(`/${action}`)).toHaveLength(0);

    await alerts.press(he.admin.cancel);
    expect(posts(`/${action}`)).toHaveLength(0);

    await fireEvent.press(screen.getByTestId(`user-${id}-${action}`));
    await alerts.press(he.admin.confirm);
    expect(posts(`/api/admin/users/${id}/${action}`)).toHaveLength(1);
  });

  it('lists pending and approved users, without actions on the admin themself', async () => {
    await renderAdmin();
    const pending = await screen.findByTestId('user-20');
    expect(within(pending).getByText(he.admin.users.requestedCity('באר שבע'))).toBeTruthy();
    expect(await screen.findByTestId('user-1')).toBeTruthy();
    expect(screen.queryByTestId('user-1-disable')).toBeNull();
    expect(screen.queryByTestId('user-1-promote')).toBeNull();
  });
});

describe('City admin (R25, R27)', () => {
  async function openCity(city = adminCity()) {
    server.on('GET', '/api/admin/cities', { status: 200, body: [city] });
    await renderAdmin('AdminCity', { cityId: 7, cityName: 'באר שבע' });
    await screen.findByTestId('set-reference');
  }

  it('explains a refused reference while a break is active (AE10)', async () => {
    server.on('POST', '/api/admin/cities/7/reference', {
      status: 409,
      body: { detail: { code: 'break_active', message: 'break active' } },
    });
    await openCity(adminCity({ line_state: 'BREAK' }));
    await fireEvent.press(screen.getByTestId('set-reference'));
    expect(await screen.findByText(he.admin.city.breakActive)).toBeTruthy();
    expect(posts('/reference')[0].body).toEqual({ confirm_short: false });
  });

  it('explains when there is no valid result', async () => {
    server.on('POST', '/api/admin/cities/7/reference', {
      status: 409,
      body: { detail: { code: 'no_valid_result', message: 'no result' } },
    });
    await openCity();
    await fireEvent.press(screen.getByTestId('set-reference'));
    expect(await screen.findByText(he.admin.city.noValidResult)).toBeTruthy();
  });

  it('asks to confirm a short fiber and retries with confirm_short', async () => {
    server.on('POST', '/api/admin/cities/7/reference', (body) =>
      body.confirm_short
        ? { status: 200, body: { reference_fiber_length_m: 4000, reference_set_at: '2026-09-30T10:00:00Z', line_state: 'OK' } }
        : {
            status: 409,
            body: {
              detail: { code: 'confirm_required', message: 'short', fiber_length_m: 4000, perimeter_m: 5000, shortfall_pct: 20 },
            },
          },
    );
    await openCity();
    await fireEvent.press(screen.getByTestId('set-reference'));
    await act(async () => undefined);

    expect(alerts.last()?.title).toBe(he.admin.city.confirmShortTitle);
    expect(alerts.last()?.message).toBe(he.admin.city.confirmShort('4,000', '5,000', '20'));
    expect(posts('/reference')).toHaveLength(1);

    await alerts.press(he.admin.confirm);
    const calls = posts('/reference');
    expect(calls).toHaveLength(2);
    expect(calls[1].body).toEqual({ confirm_short: true });
    expect(await screen.findByText(he.admin.city.referenceSet('4,000'))).toBeTruthy();
  });

  it('asks before re-baselining a city that already has a reference', async () => {
    server.on('POST', '/api/admin/cities/7/reference', {
      status: 200,
      body: { reference_fiber_length_m: 5000, reference_set_at: '2026-09-30T10:00:00Z', line_state: 'OK' },
    });
    await openCity(adminCity({ reference_fiber_length_m: 4990, reference_set_at: '2026-09-01T10:00:00Z', line_state: 'OK' }));
    await fireEvent.press(screen.getByTestId('set-reference'));
    expect(alerts.last()?.message).toBe(he.admin.city.confirmRebaseline);
    expect(posts('/reference')).toHaveLength(0);
    await alerts.press(he.admin.confirm);
    expect(posts('/reference')).toHaveLength(1);
  });

  it('saves the launch offset and break tolerance', async () => {
    server.on('PATCH', '/api/admin/cities/7', { status: 200, body: adminCity({ launch_offset_m: 45, break_tolerance_m: 25 }) });
    await openCity();
    await fireEvent.changeText(screen.getByTestId('city-launch-offset'), '45');
    await fireEvent.changeText(screen.getByTestId('city-break-tolerance'), '25');
    await fireEvent.press(screen.getByTestId('save-city-settings'));
    await act(async () => undefined);
    const patch = server.calls.find((c) => c.method === 'PATCH')!;
    expect(patch.body).toEqual({ launch_offset_m: 45, break_tolerance_m: 25 });
  });

  it('rotates the device key after confirmation and shows it once, blocking back until saved', async () => {
    server.on('POST', '/api/admin/cities/7/device-key', {
      status: 201,
      body: { device_id: 3, city_id: 7, api_key: 'secret-key-abc' },
    });
    const share = jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction' } as any);
    await openCity(adminCity({ has_device: true, device_key_rotated_at: '2026-09-01T10:00:00Z' }));

    await fireEvent.press(screen.getByTestId('device-key'));
    expect(alerts.last()?.message).toBe(he.admin.city.confirmRotate);
    expect(posts('/device-key')).toHaveLength(0);
    await alerts.press(he.admin.confirm);

    expect(await screen.findByText('secret-key-abc')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('copy-key'));
    expect(Clipboard.setStringAsync).toHaveBeenCalledWith('secret-key-abc');
    await fireEvent.press(screen.getByTestId('share-key'));
    expect(share).toHaveBeenCalledWith(expect.objectContaining({ message: 'secret-key-abc' }));

    // Leaving before confirming is blocked.
    alerts.spy.mockClear();
    await act(async () => adminNav.goBack());
    expect(adminNav.getCurrentRoute()?.name).toBe('DeviceKey');
    expect(alerts.last()?.title).toBe(he.admin.deviceKey.blockTitle);

    await fireEvent.press(screen.getByTestId('key-saved'));
    expect(adminNav.getCurrentRoute()?.name).toBe('AdminCity');
    expect(screen.queryByText('secret-key-abc')).toBeNull();
    share.mockRestore();
  });

  it('creates a device without a rotation prompt when the city has none', async () => {
    server.on('POST', '/api/admin/cities/7/device-key', {
      status: 201,
      body: { device_id: 4, city_id: 7, api_key: 'first-key' },
    });
    await openCity();
    await fireEvent.press(screen.getByTestId('device-key'));
    expect(await screen.findByText('first-key')).toBeTruthy();
    expect(alerts.spy).not.toHaveBeenCalled();
  });

  it('creates a city from the admin home', async () => {
    server.on('POST', '/api/admin/cities', { status: 201, body: adminCity({ id: 12, name: 'צפת' }) });
    await renderAdmin();
    await fireEvent.changeText(await screen.findByTestId('new-city-name'), 'צפת');
    await fireEvent.press(screen.getByTestId('create-city'));
    await act(async () => undefined);
    const call = server.calls.find((c) => c.method === 'POST' && c.path === '/api/admin/cities')!;
    expect(call.body).toEqual({ name: 'צפת' });
  });
});
