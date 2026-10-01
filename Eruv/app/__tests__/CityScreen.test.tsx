import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { CityScreen } from '../src/screens/city/CityScreen';
import { resetNotificationStore } from '../src/notifications';
import { resetAuthStore, useAuthStore } from '../src/state/auth';
import { cityStatus, installFakeServer, poles, user, type FakeServer } from '../test-utils/server';

// The automatic mock in __mocks__/react-native-webview.tsx records injected scripts.
const webview = require('react-native-webview') as { __injected: string[] };
let server: FakeServer;

const BREAK_STATUS = {
  ...cityStatus(7),
  line_state: 'BREAK',
  display_line_state: 'BREAK',
  last_result_at: new Date().toISOString(),
  active_break: {
    event_id: 5,
    occurred_at: '2026-09-30T09:00:00Z',
    replayed: false,
    mapping: { kind: 'between', pole_a: 2, pole_b: 3, lat: 31.2505, lon: 34.793, geo_distance_m: 400, offset_from_a_m: 120 },
  },
};

beforeEach(() => {
  resetAuthStore();
  resetNotificationStore();
  webview.__injected.length = 0;
  server = installFakeServer();
  useAuthStore.setState({ phase: 'signedIn', user: user() as any, accessToken: 'access-1', refreshToken: 'r', activeCityId: 7 });
});

/** The message in the last `window.eruvReceive("<json>"); true;` injection. */
function lastRender() {
  const script = webview.__injected[webview.__injected.length - 1];
  const arg = /^window\.eruvReceive\((.*)\); true;$/.exec(script)![1];
  return JSON.parse(JSON.parse(arg));
}

describe('CityScreen (R15, R17)', () => {
  it('shows the break banner and sends ring, X and bounding poles to the map', async () => {
    server.on('GET', '/api/cities/7/status', { status: 200, body: BREAK_STATUS });
    server.on('GET', '/api/cities/7/poles', { status: 200, body: poles() });
    await render(<CityScreen />);

    expect(await screen.findByTestId('banner-title')).toHaveTextContent('קרע בין עמוד 2 לעמוד 3');
    const poleCall = server.calls.find((c) => c.path === '/api/cities/7/poles');
    expect(poleCall?.headers.Authorization).toBe('Bearer access-1');

    const web = screen.getByTestId('webview');
    // Tile policy: page served under the API origin (Referer) with an identifying UA.
    expect(web.props.source.baseUrl).toBe('https://api.test/');
    expect(web.props.applicationNameForUserAgent).toBe('EruvMonitor/1.0');

    expect(webview.__injected).toHaveLength(0); // nothing until the page is ready
    await act(async () => web.props.onMessage({ nativeEvent: { data: JSON.stringify({ type: 'ready' }) } }));
    const sent = lastRender();
    expect(sent).toEqual({
      type: 'render',
      poles: poles(),
      breakPoint: { lat: 31.2505, lon: 34.793, poles: [2, 3] },
      view: 'break',
    });

    await fireEvent.press(screen.getByTestId('map-toggle-view'));
    const whole = lastRender();
    expect(whole.view).toBe('ring');
  });

  it('shows a loading skeleton until the first status arrives', async () => {
    let answer!: (v: { status: number; body: unknown }) => void;
    server.on('GET', '/api/cities/7/status', () => new Promise((r) => (answer = r)));
    server.on('GET', '/api/cities/7/poles', { status: 200, body: poles() });
    await render(<CityScreen />);
    expect(screen.getByTestId('city-loading')).toBeTruthy();
    await act(async () => answer({ status: 200, body: cityStatus(7) }));
    expect(await screen.findByText('העירוב תקין')).toBeTruthy();
    expect(screen.queryByTestId('city-loading')).toBeNull();
    expect(screen.queryByTestId('map-toggle-view')).toBeNull();
  });
});
