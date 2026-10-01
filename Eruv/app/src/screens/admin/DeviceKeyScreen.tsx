// Device key (R25): the plaintext key is shown once, after create or rotate. Copy and
// share it; leaving is blocked until the admin confirms "I saved the key".
import { useNavigation, useRoute, type NavigationProp, type RouteProp } from '@react-navigation/native';
import * as Clipboard from 'expo-clipboard';
import { useEffect, useRef, useState } from 'react';
import { Alert, Share, StyleSheet, Text, View } from 'react-native';

import { Button, colors, Screen } from '../../components/ui';
import { he } from '../../i18n/he';
import type { AdminStackParams } from '../../navigation/types';
import { ActionButton, adminStyles } from './common';

export function DeviceKeyScreen() {
  const navigation = useNavigation<NavigationProp<AdminStackParams>>();
  const { apiKey, deviceId, cityName } = useRoute<RouteProp<AdminStackParams, 'DeviceKey'>>().params;
  const saved = useRef(false);
  const [copied, setCopied] = useState(false);

  // Back button, swipe, hardware back and tab re-press all go through beforeRemove.
  useEffect(
    () =>
      navigation.addListener('beforeRemove', (event) => {
        if (saved.current) return;
        event.preventDefault();
        Alert.alert(he.admin.deviceKey.blockTitle, he.admin.deviceKey.blockBody, [{ text: he.admin.ok }]);
      }),
    [navigation],
  );

  async function copy() {
    await Clipboard.setStringAsync(apiKey);
    setCopied(true);
  }

  function done() {
    saved.current = true;
    navigation.goBack();
  }

  return (
    <Screen>
      <Text style={adminStyles.note}>{he.admin.deviceKey.explain}</Text>
      <Text style={adminStyles.cardTitle}>{he.admin.deviceKey.device(deviceId, cityName)}</Text>
      <View style={styles.keyBox}>
        <Text testID="device-api-key" selectable style={styles.key}>
          {apiKey}
        </Text>
      </View>
      <View style={adminStyles.actions}>
        <ActionButton
          testID="copy-key"
          title={copied ? he.admin.deviceKey.copied : he.admin.deviceKey.copy}
          onPress={() => void copy()}
        />
        <ActionButton testID="share-key" title={he.admin.deviceKey.share} onPress={() => void Share.share({ message: apiKey })} />
      </View>
      <Button testID="key-saved" title={he.admin.deviceKey.saved} onPress={done} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  keyBox: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, backgroundColor: colors.selected },
  key: { fontFamily: 'monospace', fontSize: 16, color: colors.text, textAlign: 'left', writingDirection: 'ltr' },
});
