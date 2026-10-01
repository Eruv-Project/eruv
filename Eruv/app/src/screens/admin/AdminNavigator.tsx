// The Admin tab's stack (admins only; the server checks the role on every admin call).
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { he } from '../../i18n/he';
import type { AdminStackParams } from '../../navigation/types';
import { AdminHomeScreen } from './AdminHomeScreen';
import { CityAdminScreen } from './CityAdminScreen';
import { DeviceKeyScreen } from './DeviceKeyScreen';
import { PoleImportScreen } from './PoleImportScreen';

const Stack = createNativeStackNavigator<AdminStackParams>();

export function AdminNavigator() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen name="AdminHome" component={AdminHomeScreen} options={{ title: he.admin.title }} />
      <Stack.Screen name="AdminCity" component={CityAdminScreen} options={({ route }) => ({ title: route.params.cityName })} />
      <Stack.Screen
        name="PoleImport"
        component={PoleImportScreen}
        options={({ route }) => ({ title: he.admin.poles.title(route.params.cityName) })}
      />
      <Stack.Screen
        name="DeviceKey"
        component={DeviceKeyScreen}
        options={{ title: he.admin.deviceKey.title, gestureEnabled: false, headerBackVisible: false }}
      />
    </Stack.Navigator>
  );
}
