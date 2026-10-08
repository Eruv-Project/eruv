// expo-notifications, or null where it cannot load.
//
// Expo Go on Android dropped remote push in SDK 53 and throws as soon as the
// module loads, which crashes the app at startup. Previewing the app in Expo Go
// therefore runs without push; development and release builds always load it.
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { Platform } from 'react-native';

type NotificationsModule = typeof import('expo-notifications');

export const pushUnavailable =
  Platform.OS === 'android' && Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

export const Notifications: NotificationsModule | null = pushUnavailable
  ? null
  : // eslint-disable-next-line @typescript-eslint/no-require-imports
    (require('expo-notifications') as NotificationsModule);
