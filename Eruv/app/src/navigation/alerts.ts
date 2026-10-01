// Tapping a push opens the City tab for that alert's city.
import { createNavigationContainerRef } from '@react-navigation/native';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';

import { alertCityId } from '../notifications';
import { isAdmin, useAuthStore } from '../state/auth';
import type { RootStackParams } from './types';

export const navigationRef = createNavigationContainerRef<RootStackParams>();

export function openAlert(response: Notifications.NotificationResponse): void {
  const cityId = alertCityId(response);
  const { user, setActiveCity } = useAuthStore.getState();
  // A maintainer only ever sees their approved city; an admin switches to the alert's city.
  if (cityId !== null && isAdmin(user)) setActiveCity(cityId);
  if (navigationRef.isReady()) navigationRef.navigate('Tabs', { screen: 'City' });
}

/** While signed in: handle taps, including the one that launched the app. */
export function useAlertNavigation(signedIn: boolean): void {
  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (active && response) {
        openAlert(response);
        void Notifications.clearLastNotificationResponseAsync();
      }
    });
    const sub = Notifications.addNotificationResponseReceivedListener(openAlert);
    return () => {
      active = false;
      sub.remove();
    };
  }, [signedIn]);
}
