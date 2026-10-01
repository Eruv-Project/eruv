// Persistent R22 warning: notifications are off or this phone has no push token on the server.
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { he } from '../i18n/he';
import { useNotificationWarning } from '../notifications';
import { colors } from './ui';

export function NotificationWarningStrip() {
  const show = useNotificationWarning();
  if (!show) return null;
  return (
    <View style={styles.strip} testID="notification-warning">
      <Text style={styles.text}>{he.notifications.warning}</Text>
      <Pressable accessibilityRole="button" onPress={() => void Linking.openSettings()} style={styles.button}>
        <Text style={styles.buttonText}>{he.notifications.openSettings}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    backgroundColor: colors.warningBg,
    borderBottomWidth: 1,
    borderBottomColor: colors.danger,
  },
  text: { flex: 1, color: colors.danger, fontSize: 14, fontWeight: '600', textAlign: 'left' },
  button: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, backgroundColor: colors.danger },
  buttonText: { color: '#fff', fontSize: 13, fontWeight: '600' },
});
