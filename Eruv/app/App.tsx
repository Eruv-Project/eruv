import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { I18nManager } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { RootNavigator } from './src/navigation/RootNavigator';
import { configureNotifications } from './src/notifications';
import { useAuthStore } from './src/state/auth';

// Hebrew UI is right-to-left (R18). app.config.ts also forces RTL natively
// (expo-localization forcesRTL) so the very first launch is already mirrored.
I18nManager.allowRTL(true);
I18nManager.forceRTL(true);
configureNotifications();

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  return (
    <SafeAreaProvider>
      <RootNavigator />
      <StatusBar style="dark" />
    </SafeAreaProvider>
  );
}
