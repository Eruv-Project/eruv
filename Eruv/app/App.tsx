import { FrankRuhlLibre_700Bold, FrankRuhlLibre_900Black, useFonts } from '@expo-google-fonts/frank-ruhl-libre';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect } from 'react';
import { I18nManager, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Splash } from './src/components/Splash';
import { colors } from './src/components/ui';
import { RootNavigator } from './src/navigation/RootNavigator';
import { configureNotifications } from './src/notifications';
import { useAuthStore } from './src/state/auth';

// Hebrew UI is right-to-left (R18). app.config.ts also forces RTL natively
// (expo-localization forcesRTL) so the very first launch is already mirrored.
I18nManager.allowRTL(true);
I18nManager.forceRTL(true);
configureNotifications();
// The native splash stays until the full-screen launch view (Splash) is on screen.
SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const phase = useAuthStore((s) => s.phase);
  const [fontsLoaded, fontError] = useFonts({ FrankRuhlLibre_700Bold, FrankRuhlLibre_900Black });
  // A font that fails to load falls back to the system font rather than blocking the app.
  const fontsSettled = fontsLoaded || fontError !== null;

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const hideNativeSplash = useCallback(() => {
    SplashScreen.hideAsync().catch(() => undefined);
  }, []);

  return (
    <SafeAreaProvider>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        {fontsSettled ? <RootNavigator /> : null}
        <Splash ready={fontsSettled && phase !== 'loading'} onShown={hideNativeSplash} />
      </View>
      <StatusBar style="light" />
    </SafeAreaProvider>
  );
}
