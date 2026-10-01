import { act, fireEvent, screen } from '@testing-library/react-native';
import * as DocumentPicker from 'expo-document-picker';

import { he } from '../src/i18n/he';
import { resetAuthStore, useAuthStore } from '../src/state/auth';
import { renderAdmin, spyAlerts } from '../test-utils/admin';
import { adminCity, installFakeServer, poles, user, type FakeServer } from '../test-utils/server';

jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));

const webview = require('react-native-webview') as { __injected: string[] };
const pick = DocumentPicker.getDocumentAsync as jest.Mock;
let server: FakeServer;
let alerts: ReturnType<typeof spyAlerts>;

beforeEach(() => {
  resetAuthStore();
  webview.__injected.length = 0;
  alerts = spyAlerts();
  server = installFakeServer();
  useAuthStore.setState({
    phase: 'signedIn',
    user: user({ id: 1, role: 'admin', approved_city_id: null }) as any,
    accessToken: 'access-1',
    refreshToken: 'r',
  });
  server.on('GET', '/api/admin/users', { status: 200, body: [] });
  server.on('GET', '/api/admin/cities', { status: 200, body: [adminCity()] });
  server.on('GET', '/api/cities', { status: 200, body: [{ id: 7, name: 'באר שבע' }] });
  pick.mockResolvedValue({
    canceled: false,
    assets: [{ uri: 'file:///cache/poles.csv', name: 'poles.csv', mimeType: 'text/csv', size: 60 }],
  });
});

afterEach(() => alerts.spy.mockRestore());

async function openImport() {
  await renderAdmin('PoleImport', { cityId: 7, cityName: 'באר שבע' });
  await fireEvent.press(await screen.findByTestId('pick-pole-file'));
}

function lastRender() {
  const script = webview.__injected[webview.__injected.length - 1];
  const arg = /^window\.eruvReceive\((.*)\); true;$/.exec(script)![1];
  return JSON.parse(JSON.parse(arg));
}

describe('Pole import (R26)', () => {
  it('uploads the picked file, previews the poles on the map, and confirm replaces them', async () => {
    server.on('POST', '/api/admin/cities/7/poles/preview', {
      status: 200,
      body: { poles: poles(), count: 3, perimeter_m: 1234.5 },
    });
    server.on('PUT', '/api/admin/cities/7/poles', { status: 200, body: { count: 3, perimeter_m: 1234.5 } });
    await openImport();

    expect(await screen.findByText(he.admin.poles.previewSummary(3, '1,234.5'))).toBeTruthy();
    const upload = server.calls.find((c) => c.path === '/api/admin/cities/7/poles/preview')!;
    expect(upload.method).toBe('POST');
    expect(upload.body).toBeInstanceOf(FormData);
    expect(upload.headers['Content-Type']).toBeUndefined();
    expect(upload.headers.Authorization).toBe('Bearer access-1');

    // The preview map gets exactly the previewed poles, with no break.
    const web = screen.getByTestId('webview');
    await act(async () => web.props.onMessage({ nativeEvent: { data: JSON.stringify({ type: 'ready' }) } }));
    expect(lastRender()).toEqual({ type: 'render', poles: poles(), breakPoint: null, view: 'ring' });

    // Saving asks first; nothing is sent before confirming.
    await fireEvent.press(screen.getByTestId('save-poles'));
    expect(alerts.last()?.message).toBe(he.admin.poles.confirmReplace(3, 'באר שבע'));
    expect(server.calls.some((c) => c.method === 'PUT')).toBe(false);
    await alerts.press(he.admin.confirm);

    const put = server.calls.find((c) => c.method === 'PUT')!;
    expect(put.path).toBe('/api/admin/cities/7/poles');
    expect(put.body).toEqual({ poles: poles() });
  });

  it('shows a 422 inline, naming the missing pole number and the failing row', async () => {
    server.on('POST', '/api/admin/cities/7/poles/preview', {
      status: 422,
      body: {
        detail: {
          code: 'invalid_poles',
          errors: [
            { row: null, message: 'pole numbers must be consecutive', missing_number: 3 },
            { row: 5, message: 'latitude out of range', missing_number: null },
          ],
        },
      },
    });
    await openImport();

    expect(await screen.findByText(he.admin.poles.missingNumber(3))).toBeTruthy();
    expect(screen.getByText(he.admin.poles.rowError(5, 'latitude out of range'))).toBeTruthy();
    expect(screen.queryByTestId('save-poles')).toBeNull();
    expect(screen.queryByTestId('webview')).toBeNull();
  });

  it('does nothing when the picker is cancelled', async () => {
    pick.mockResolvedValue({ canceled: true, assets: null });
    await openImport();
    await act(async () => undefined);
    expect(server.calls.some((c) => c.path.includes('/poles/preview'))).toBe(false);
  });
});
