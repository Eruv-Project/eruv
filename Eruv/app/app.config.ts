import type { ExpoConfig } from 'expo/config';
import { withAndroidManifest, type ConfigPlugin } from 'expo/config-plugins';

// Android 11+ hides other apps from Linking.canOpenURL unless declared: lets the
// break screen detect Waze (`waze://`) and fall back to Google Maps otherwise (R17).
const withWazeQuery: ConfigPlugin = (cfg) =>
  withAndroidManifest(cfg, (mod) => {
    const manifest = mod.modResults.manifest;
    manifest.queries = manifest.queries ?? [];
    manifest.queries.push({
      intent: [{ action: [{ $: { 'android:name': 'android.intent.action.VIEW' } }], data: [{ $: { 'android:scheme': 'waze' } }] }],
    } as (typeof manifest.queries)[number]);
    return mod;
  });

// The API base URL is NOT configured here: it comes only from EXPO_PUBLIC_API_URL
// (see .env.example), which Expo inlines into the bundle at build time.
// EAS_PROJECT_ID is written by `eas init`; push tokens need it (getExpoPushTokenAsync).
const easProjectId = process.env.EAS_PROJECT_ID;

const config: ExpoConfig = {
  name: 'עירוב',
  slug: 'eruv-monitor',
  scheme: 'eruv',
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'light',
  ios: {
    bundleIdentifier: 'com.eruv.monitor',
    supportsTablet: false,
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      // Linking.canOpenURL('waze://') needs the scheme declared (R17).
      LSApplicationQueriesSchemes: ['waze'],
    },
  },
  android: {
    package: 'com.eruv.monitor',
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
  },
  plugins: [
    'expo-secure-store',
    'expo-notifications',
    // Hebrew UI: native right-to-left layout from the first launch (R18).
    ['expo-localization', { supportsRTL: true, forcesRTL: true }],
  ],
  extra: {
    eas: easProjectId ? { projectId: easProjectId } : undefined,
  },
};

export default withWazeQuery(config);
