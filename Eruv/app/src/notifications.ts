// Push notifications: permission, Expo push token registration with the server,
// the R22 warning flag, and reading the city from a tapped alert.
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';
import { create } from 'zustand';

import { api } from './api/client';

export type PermissionState = 'granted' | 'denied' | 'undetermined';

interface NotificationState {
  /** null until the first check has finished. */
  permission: PermissionState | null;
  tokenRegistered: boolean;
  /** The Expo push token last registered with the server, for unregistering at logout. */
  token: string | null;
}

export const useNotificationStore = create<NotificationState>()(() => ({
  permission: null,
  tokenRegistered: false,
  token: null,
}));

export function resetNotificationStore(): void {
  useNotificationStore.setState({ permission: null, tokenRegistered: false, token: null });
}

/** True when the persistent R22 warning must show: permission off or no token on the server. */
export function useNotificationWarning(): boolean {
  return useNotificationStore((s) => s.permission !== null && (s.permission !== 'granted' || !s.tokenRegistered));
}

let handlerConfigured = false;

/** Show alerts that arrive while the app is open. Called once at startup. */
export function configureNotifications(): void {
  if (handlerConfigured) return;
  handlerConfigured = true;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

function easProjectId(): string | undefined {
  return Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

/**
 * Check (and when asked, request) permission, then register the Expo push token
 * with the server. Runs after login and on every return to the foreground.
 */
export async function syncPushRegistration({ requestPermission }: { requestPermission: boolean }): Promise<void> {
  if (Platform.OS === 'android') {
    // Android 13+ shows the permission prompt only once a channel exists.
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.MAX,
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted' && requestPermission) {
    ({ status } = await Notifications.requestPermissionsAsync());
  }
  const permission = status as PermissionState;
  if (permission !== 'granted') {
    useNotificationStore.setState({ permission, tokenRegistered: false });
    return;
  }
  let tokenRegistered = false;
  let token: string | null = null;
  try {
    token = await fetchExpoPushToken();
    await api.registerPushToken(token, Platform.OS);
    tokenRegistered = true;
  } catch {
    // Missing projectId, no network, or the server refused: the warning stays up
    // and the next foreground tries again.
  }
  // The token is kept even when the server refused it, so logout can still unregister it.
  useNotificationStore.setState({ permission, tokenRegistered, token });
}

async function fetchExpoPushToken(): Promise<string> {
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId: easProjectId() });
  return data;
}

/** This phone's Expo push token: the one last registered, else asked of Expo; null when unavailable. */
async function currentPushToken(): Promise<string | null> {
  const known = useNotificationStore.getState().token;
  if (known) return known;
  try {
    const { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted') return null;
    return await fetchExpoPushToken();
  } catch {
    return null;
  }
}

/**
 * At logout: best-effort removal of this phone's push token from the server so it
 * stops receiving the city's alerts. Never throws; logout must work offline.
 */
export async function unregisterPushToken(): Promise<void> {
  try {
    const token = await currentPushToken();
    if (token) await api.unregisterPushToken(token);
  } catch {
    // No network or the server refused: nothing more to do on this phone.
  }
  resetNotificationStore();
}

/** While signed in: register after login (asking for permission), re-check on every foreground. */
export function useNotificationSync(signedIn: boolean): void {
  useEffect(() => {
    if (!signedIn) return;
    void syncPushRegistration({ requestPermission: true });
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') void syncPushRegistration({ requestPermission: false });
    });
    return () => sub.remove();
  }, [signedIn]);
}

/** The city an alert is about. The server sends `data.city_id` with every push (U6). */
export function alertCityId(response: Notifications.NotificationResponse): number | null {
  const raw = (response.notification.request.content.data as Record<string, unknown> | undefined)?.city_id;
  const id = typeof raw === 'string' ? Number(raw) : raw;
  return typeof id === 'number' && Number.isInteger(id) ? id : null;
}
