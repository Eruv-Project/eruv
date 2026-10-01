import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as Notifications from 'expo-notifications';
import { createElement } from 'react';
import { AppState, Linking } from 'react-native';

import { NotificationWarningStrip } from '../src/components/NotificationWarningStrip';
import { he } from '../src/i18n/he';
import { alertCityId, resetNotificationStore, useNotificationStore, useNotificationSync } from '../src/notifications';
import { resetAuthStore, useAuthStore } from '../src/state/auth';
import { installFakeServer, type FakeServer } from '../test-utils/server';

const notif = Notifications as unknown as {
  __state: { status: string; requestResult: string; token: string };
  __reset(): void;
};

let server: FakeServer;
let appStateListener: ((s: string) => void) | null;

function Harness() {
  useNotificationSync(true);
  return createElement(NotificationWarningStrip);
}

beforeEach(() => {
  notif.__reset();
  resetNotificationStore();
  resetAuthStore();
  useAuthStore.setState({ phase: 'signedIn', accessToken: 'access-1', refreshToken: 'refresh-1' });
  server = installFakeServer();
  server.on('POST', '/api/push-tokens', { status: 201, body: {} });
  appStateListener = null;
  jest.spyOn(AppState, 'addEventListener').mockImplementation(((_type: string, listener: (s: string) => void) => {
    appStateListener = listener;
    return { remove: jest.fn() };
  }) as never);
});

afterEach(() => jest.restoreAllMocks());

const pushTokenCalls = () => server.calls.filter((c) => c.path === '/api/push-tokens');

it('shows the warning strip when permission is denied, with a button to the phone settings', async () => {
  notif.__state.requestResult = 'denied';
  const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
  await render(createElement(Harness));

  expect(await screen.findByText(he.notifications.warning)).toBeTruthy();
  expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
  expect(pushTokenCalls()).toHaveLength(0);

  await fireEvent.press(screen.getByText(he.notifications.openSettings));
  expect(openSettings).toHaveBeenCalled();
});

it('hides the warning and registers the token after permission is granted and the app returns', async () => {
  notif.__state.requestResult = 'denied';
  await render(createElement(Harness));
  await screen.findByText(he.notifications.warning);

  // The user turns notifications on in the phone settings, then comes back.
  notif.__state.status = 'granted';
  await act(async () => {
    appStateListener?.('active');
  });

  await waitFor(() => expect(screen.queryByText(he.notifications.warning)).toBeNull());
  expect(pushTokenCalls()).toHaveLength(1);
  expect(pushTokenCalls()[0].body).toEqual({ token: 'ExponentPushToken[test]', platform: 'ios' });
  expect(pushTokenCalls()[0].headers.Authorization).toBe('Bearer access-1');
  // Foreground re-checks do not prompt again.
  expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
});

it('keeps the warning when permission is granted but the token cannot be registered', async () => {
  notif.__state.requestResult = 'granted';
  server.on('POST', '/api/push-tokens', { status: 500, body: {} });
  await render(createElement(Harness));

  expect(await screen.findByText(he.notifications.warning)).toBeTruthy();
  expect(pushTokenCalls()).toHaveLength(1);
});

it('reads the alert city from the push payload', () => {
  const response = (data: unknown) => ({ notification: { request: { content: { data } } } }) as never;
  expect(alertCityId(response({ city_id: 7 }))).toBe(7);
  expect(alertCityId(response({ city_id: '9' }))).toBe(9);
  expect(alertCityId(response({}))).toBeNull();
});

describe('logout', () => {
  const deleteCalls = () => server.calls.filter((c) => c.path === '/api/push-tokens' && c.method === 'DELETE');

  it('unregisters the push token from the server before signing out', async () => {
    notif.__state.requestResult = 'granted';
    server.on('DELETE', '/api/push-tokens', { status: 204 });
    await render(createElement(Harness));
    await waitFor(() => expect(pushTokenCalls()).toHaveLength(1));

    await act(async () => {
      await useAuthStore.getState().logout();
    });

    expect(deleteCalls()).toHaveLength(1);
    expect(deleteCalls()[0].body).toEqual({ token: 'ExponentPushToken[test]' });
    expect(deleteCalls()[0].headers.Authorization).toBe('Bearer access-1');
    expect(useAuthStore.getState().phase).toBe('signedOut');
    expect(useNotificationStore.getState()).toMatchObject({ permission: null, tokenRegistered: false, token: null });
  });

  it('asks Expo for the token when none was registered yet', async () => {
    notif.__state.status = 'granted';
    server.on('DELETE', '/api/push-tokens', { status: 204 });
    await useAuthStore.getState().logout();
    expect(deleteCalls()).toHaveLength(1);
    expect(deleteCalls()[0].body).toEqual({ token: 'ExponentPushToken[test]' });
  });

  it('still signs out when the server cannot be reached', async () => {
    useNotificationStore.setState({ permission: 'granted', tokenRegistered: true, token: 'ExponentPushToken[test]' });
    server.on('DELETE', '/api/push-tokens', () => {
      throw new TypeError('Network request failed');
    });
    await useAuthStore.getState().logout();
    expect(deleteCalls()).toHaveLength(1);
    expect(useAuthStore.getState()).toMatchObject({ phase: 'signedOut', accessToken: null, refreshToken: null });
    expect(useNotificationStore.getState().token).toBeNull();
  });
});
