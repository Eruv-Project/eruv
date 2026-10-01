// Renders the Admin tab's stack in a bare navigation container, with a ref to drive it.
import { createNavigationContainerRef, NavigationContainer } from '@react-navigation/native';
import { act, render } from '@testing-library/react-native';
import { Alert, type AlertButton } from 'react-native';

import type { AdminStackParams } from '../src/navigation/types';
import { AdminNavigator } from '../src/screens/admin/AdminNavigator';

export const adminNav = createNavigationContainerRef<AdminStackParams>();

export async function renderAdmin<K extends keyof AdminStackParams>(
  route?: K,
  params?: AdminStackParams[K],
) {
  const result = await render(
    <NavigationContainer ref={adminNav}>
      <AdminNavigator />
    </NavigationContainer>,
  );
  if (route) await act(async () => (adminNav.navigate as any)(route, params));
  return result;
}

/** Spy on Alert.alert; `press(title-substring, buttonText)` taps a button of the last matching alert. */
export function spyAlerts() {
  const spy = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  return {
    spy,
    last(): { title: string; message?: string; buttons: AlertButton[] } | undefined {
      const call = spy.mock.calls[spy.mock.calls.length - 1];
      return call ? { title: call[0], message: call[1], buttons: (call[2] ?? []) as AlertButton[] } : undefined;
    },
    async press(buttonText: string) {
      const alert = this.last();
      const button = alert?.buttons.find((b) => b.text === buttonText);
      if (!button) throw new Error(`no alert button "${buttonText}" in ${JSON.stringify(alert)}`);
      await act(async () => button.onPress?.());
    },
  };
}
