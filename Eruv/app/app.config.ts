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
// The EAS project (`eas init`, owner below). Push tokens need its id
// (getExpoPushTokenAsync); it is not a secret.
const EAS_PROJECT_ID = '4682a724-db49-4509-982a-6632201d8e1e';

const config: ExpoConfig = {
  name: 'עירוב',
  slug: 'eruv-monitor',
  owner: 'eruvshabbats-team',
  scheme: 'eruv',
  version: '1.0.0',
  // Over-the-air updates (EAS Update): screens, texts, design and fixes reach
  // installed phones without a new APK. The fingerprint runtime version changes
  // whenever native code changes (a new module, permission, icon), so an update
  // is only offered to builds that can run it; those changes still need a build.
  runtimeVersion: { policy: 'fingerprint' },
  updates: {
    url: `https://u.expo.dev/${EAS_PROJECT_ID}`,
    // Check on every launch; a downloaded update applies on the next launch.
    checkAutomatically: 'ON_LOAD',
    fallbackToCacheTimeout: 0,
  },
  orientation: 'portrait',
  icon: './assets/icon.png',
  // The app is drawn on the icon's night navy; system dialogs follow it.
  userInterfaceStyle: 'dark',
  backgroundColor: '#0C182A',
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
    // Firebase project "Eruv Shabbat": Android push (FCM) for Expo notifications.
    googleServicesFile: './google-services.json',
    adaptiveIcon: {
      backgroundColor: '#0C182A',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
  },
  plugins: [
    'expo-secure-store',
    // Native launch screen: the icon on the night ground (src/components/Splash.tsx
    // then shows the artwork full screen).
    [
      'expo-splash-screen',
      { backgroundColor: '#0C182A', image: './assets/icon.png', imageWidth: 200, resizeMode: 'contain' },
    ],
    'expo-system-ui',
    'expo-font',
    'expo-notifications',
    // Foreground location only: the maintainer's own dot on the City map.
    [
      'expo-location',
      {
        locationWhenInUsePermission: 'המיקום שלך מוצג על מפת העירוב, כדי שתראה איפה אתה ביחס לקרע.',
        isAndroidBackgroundLocationEnabled: false,
        isIosBackgroundLocationEnabled: false,
      },
    ],
    // Hebrew UI: native right-to-left layout from the first launch (R18).
    ['expo-localization', { supportsRTL: true, forcesRTL: true }],
  ],
  extra: {
    eas: { projectId: EAS_PROJECT_ID },
  },
};

export default withWazeQuery(config);
