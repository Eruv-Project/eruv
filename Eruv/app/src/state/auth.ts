// Auth store: session tokens (expo-secure-store), the approval phase that drives
// navigation, and the city the City/Logs tabs show.
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

import {
  api,
  ApiError,
  bindSession,
  notApprovedState,
  type RegisterInput,
  type SessionEndReason,
  type TokenPair,
  type User,
} from '../api/client';
import { resetNotificationStore, unregisterPushToken } from '../notifications';

/** Which part of the app the user may see. Only `signedIn` reaches the tabs. */
export type AuthPhase = 'loading' | 'signedOut' | 'pending' | 'rejected' | 'disabled' | 'signedIn';

export const STORAGE_KEYS = {
  access: 'eruv.access_token',
  refresh: 'eruv.refresh_token',
  user: 'eruv.user',
  // Secret for POST /registration-status; issued by register and city-change.
  registration: 'eruv.registration_token',
} as const;

interface AuthState {
  phase: AuthPhase;
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  registrationToken: string | null;
  /** City shown on City/Logs: the approved city, or the admin's switcher choice. */
  activeCityId: number | null;
  /** Why the login screen is showing, when it needs saying. */
  loginNotice: 'approved' | null;

  bootstrap(): Promise<void>;
  login(email: string, password: string): Promise<void>;
  register(input: RegisterInput): Promise<void>;
  /** Poll step for the pending screen. */
  checkRegistration(): Promise<void>;
  requestCityChange(cityId: number): Promise<void>;
  logout(): Promise<void>;
  endSession(reason: SessionEndReason): Promise<void>;
  setActiveCity(cityId: number): void;
  goToLogin(notice?: 'approved' | null): void;
}

const initialState = {
  phase: 'loading' as AuthPhase,
  user: null,
  accessToken: null,
  refreshToken: null,
  registrationToken: null,
  activeCityId: null,
  loginNotice: null as 'approved' | null,
};

async function writeSecure(key: string, value: string | null): Promise<void> {
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}

async function clearSession(): Promise<void> {
  await Promise.all([
    writeSecure(STORAGE_KEYS.access, null),
    writeSecure(STORAGE_KEYS.refresh, null),
    writeSecure(STORAGE_KEYS.user, null),
  ]);
}

async function storePair(pair: TokenPair): Promise<void> {
  await Promise.all([
    writeSecure(STORAGE_KEYS.access, pair.access_token),
    writeSecure(STORAGE_KEYS.refresh, pair.refresh_token),
    writeSecure(STORAGE_KEYS.user, JSON.stringify(pair.user)),
  ]);
}

const signedOutSession = { user: null, accessToken: null, refreshToken: null, activeCityId: null };

export const useAuthStore = create<AuthState>()((set, get) => {
  async function enterPending(registrationToken: string | null): Promise<void> {
    await clearSession();
    if (registrationToken) await writeSecure(STORAGE_KEYS.registration, registrationToken);
    set((s) => ({
      ...signedOutSession,
      phase: 'pending',
      registrationToken: registrationToken ?? s.registrationToken,
    }));
  }

  return {
    ...initialState,

    async bootstrap() {
      const [access, refresh, userJson, registration] = await Promise.all([
        SecureStore.getItemAsync(STORAGE_KEYS.access),
        SecureStore.getItemAsync(STORAGE_KEYS.refresh),
        SecureStore.getItemAsync(STORAGE_KEYS.user),
        SecureStore.getItemAsync(STORAGE_KEYS.registration),
      ]);
      set({ registrationToken: registration });
      if (!refresh) {
        set({ phase: registration ? 'pending' : 'signedOut' });
        return;
      }
      const cached: User | null = userJson ? JSON.parse(userJson) : null;
      set({ accessToken: access, refreshToken: refresh, user: cached, activeCityId: cached?.approved_city_id ?? null });
      try {
        const user = await api.me();
        await writeSecure(STORAGE_KEYS.user, JSON.stringify(user));
        set((s) => ({ user, phase: 'signedIn', activeCityId: s.activeCityId ?? user.approved_city_id }));
      } catch (err) {
        // A rejected session was already routed by endSession(); a network failure
        // keeps the cached session so the app still opens without signal.
        if (!(err instanceof ApiError) && cached && get().phase === 'loading') set({ phase: 'signedIn' });
        else if (get().phase === 'loading') set({ ...signedOutSession, phase: 'signedOut' });
      }
    },

    async login(email, password) {
      try {
        const pair = await api.login(email.trim(), password);
        await storePair(pair);
        await writeSecure(STORAGE_KEYS.registration, null);
        set({
          phase: 'signedIn',
          user: pair.user,
          accessToken: pair.access_token,
          refreshToken: pair.refresh_token,
          activeCityId: pair.user.approved_city_id,
          registrationToken: null,
          loginNotice: null,
        });
      } catch (err) {
        const state = notApprovedState(err);
        if (state === 'pending') await enterPending(null);
        else if (state === 'rejected' || state === 'disabled') set({ phase: state });
        else throw err;
      }
    },

    async register(input) {
      const result = await api.register(input);
      await enterPending(result.registration_token);
    },

    async checkRegistration() {
      const token = get().registrationToken;
      if (!token || get().phase !== 'pending') return;
      try {
        const { approval_state } = await api.registrationStatus(token);
        if (get().phase !== 'pending') return;
        if (approval_state === 'approved') {
          await writeSecure(STORAGE_KEYS.registration, null);
          set({ registrationToken: null });
          get().goToLogin('approved');
        } else if (approval_state === 'rejected' || approval_state === 'disabled') {
          set({ phase: approval_state });
        }
      } catch (err) {
        // The token was replaced (e.g. a city change from another device): log in again.
        if (err instanceof ApiError && err.status === 404) {
          await writeSecure(STORAGE_KEYS.registration, null);
          set({ registrationToken: null });
          get().goToLogin(null);
        }
      }
    },

    async requestCityChange(cityId) {
      const result = await api.cityChange(cityId);
      await enterPending(result.registration_token);
    },

    async logout() {
      // While the session still authorizes it, so this phone stops getting the city's alerts.
      if (get().accessToken || get().refreshToken) await unregisterPushToken();
      else resetNotificationStore();
      await clearSession();
      await writeSecure(STORAGE_KEYS.registration, null);
      set({ ...signedOutSession, registrationToken: null, phase: 'signedOut', loginNotice: null });
    },

    async endSession(reason) {
      await clearSession();
      set({ ...signedOutSession, phase: reason === 'expired' ? 'signedOut' : reason });
    },

    setActiveCity(cityId) {
      set({ activeCityId: cityId });
    },

    goToLogin(notice = null) {
      set({ phase: 'signedOut', loginNotice: notice });
    },
  };
});

bindSession({
  accessToken: () => useAuthStore.getState().accessToken,
  refreshToken: () => useAuthStore.getState().refreshToken,
  onRefreshed: async (pair) => {
    await storePair(pair);
    useAuthStore.setState({ accessToken: pair.access_token, refreshToken: pair.refresh_token, user: pair.user });
  },
  onSessionEnded: (reason) => {
    void useAuthStore.getState().endSession(reason);
  },
});

export function isAdmin(user: User | null): boolean {
  return user?.role === 'admin';
}

/** Test helper: back to a fresh, not-yet-bootstrapped store. */
export function resetAuthStore(): void {
  useAuthStore.setState(initialState);
}
