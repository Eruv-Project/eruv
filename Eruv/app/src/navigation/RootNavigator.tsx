// Root navigation. The auth phase decides which screens exist; switching phase
// (login, approval, disable, city change) swaps the whole screen set, so a user
// who is not approved has no route to the tabs (R20).
import { Ionicons } from '@expo/vector-icons';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import type { ComponentProps } from 'react';
import { View } from 'react-native';

import { colors } from '../components/ui';
import { he } from '../i18n/he';
import { useNotificationSync } from '../notifications';
import { DisabledScreen, RejectedScreen } from '../screens/auth/BlockedScreens';
import { CityChangeScreen } from '../screens/auth/CityPickerScreen';
import { LoginScreen } from '../screens/auth/LoginScreen';
import { PendingScreen } from '../screens/auth/PendingScreen';
import { RegisterScreen } from '../screens/auth/RegisterScreen';
import { CityScreen } from '../screens/city/CityScreen';
import { AdminNavigator } from '../screens/admin/AdminNavigator';
import { LogsScreen } from '../screens/logs/LogsScreen';
import { SettingsScreen } from '../screens/settings/SettingsScreen';
import { isAdmin, useAuthStore } from '../state/auth';
import { navigationRef, useAlertNavigation } from './alerts';
import { headerOptions, theme } from './theme';
import type { MainTabParams, RootStackParams } from './types';

const Stack = createNativeStackNavigator<RootStackParams>();

const Tab = createBottomTabNavigator<MainTabParams>();

type IconName = ComponentProps<typeof Ionicons>['name'];

/** Tab icons: outline when idle, filled when selected. */
const TAB_ICONS: Record<keyof MainTabParams, [IconName, IconName]> = {
  City: ['business-outline', 'business'],
  Logs: ['document-text-outline', 'document-text'],
  Settings: ['settings-outline', 'settings'],
  Admin: ['shield-checkmark-outline', 'shield-checkmark'],
};

function MainTabs() {
  const admin = useAuthStore((s) => isAdmin(s.user));
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        ...headerOptions,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
        tabBarLabelStyle: { fontSize: 12, fontWeight: '600' },
        tabBarIcon: ({ focused, color, size }) => (
          <Ionicons name={TAB_ICONS[route.name][focused ? 1 : 0]} size={size} color={color} />
        ),
      })}
    >
      <Tab.Screen name="City" component={CityScreen} options={{ title: he.tabs.city }} />
      <Tab.Screen name="Logs" component={LogsScreen} options={{ title: he.tabs.logs }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: he.tabs.settings }} />
      {admin ? <Tab.Screen name="Admin" component={AdminNavigator} options={{ title: he.tabs.admin, headerShown: false }} /> : null}
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const phase = useAuthStore((s) => s.phase);
  const signedIn = phase === 'signedIn';
  useNotificationSync(signedIn);
  useAlertNavigation(signedIn);

  // The launch view (components/Splash.tsx) covers this until the session is known.
  if (phase === 'loading') return <View style={{ flex: 1, backgroundColor: colors.background }} />;

  return (
    <NavigationContainer ref={navigationRef} theme={theme}>
      <Stack.Navigator screenOptions={headerOptions}>
        {phase === 'signedIn' ? (
          <>
            <Stack.Screen name="Tabs" component={MainTabs} options={{ headerShown: false }} />
            <Stack.Screen name="CityChange" component={CityChangeScreen} options={{ title: he.cityPicker.title }} />
          </>
        ) : phase === 'pending' ? (
          <Stack.Screen name="Pending" component={PendingScreen} options={{ headerShown: false }} />
        ) : phase === 'rejected' ? (
          <Stack.Screen name="Rejected" component={RejectedScreen} options={{ headerShown: false }} />
        ) : phase === 'disabled' ? (
          <Stack.Screen name="Disabled" component={DisabledScreen} options={{ headerShown: false }} />
        ) : (
          <>
            <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
            <Stack.Screen name="Register" component={RegisterScreen} options={{ title: he.register.title }} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
