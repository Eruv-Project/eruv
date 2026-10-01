import type { NavigatorScreenParams } from '@react-navigation/native';

/** Bottom tabs for approved users. Admin is registered only for admins. */
export type MainTabParams = {
  City: undefined;
  Logs: undefined;
  Settings: undefined;
  Admin: NavigatorScreenParams<AdminStackParams> | undefined;
};

/** The Admin tab's own stack (admins only). */
export type AdminStackParams = {
  AdminHome: undefined;
  AdminCity: { cityId: number; cityName: string };
  PoleImport: { cityId: number; cityName: string };
  /** The plaintext key lives only in these params, so it is gone once the screen closes (R25). */
  DeviceKey: { cityName: string; deviceId: number; apiKey: string };
};

/**
 * One root stack. Which screens exist depends on the auth phase, so a pending,
 * rejected or disabled user has no route to the tabs at all (R20).
 */
export type RootStackParams = {
  // signed out
  Login: undefined;
  Register: undefined;
  // approval gate
  Pending: undefined;
  Rejected: undefined;
  Disabled: undefined;
  // signed in
  Tabs: NavigatorScreenParams<MainTabParams> | undefined;
  CityChange: undefined;
};
