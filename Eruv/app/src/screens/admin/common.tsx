// Shared pieces of the admin screens: confirmation dialog, section heading, small action button.
import type { ReactNode } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, errorTextStyle } from '../../components/ui';
import { he } from '../../i18n/he';

/** Ask before a consequential admin action (plan U9 step 4). Nothing runs on cancel. */
export function confirmAction(message: string, onConfirm: () => void, title: string = he.admin.title): void {
  Alert.alert(title, message, [
    { text: he.admin.cancel, style: 'cancel' },
    { text: he.admin.confirm, onPress: onConfirm },
  ]);
}

export function Section({ title, children, testID }: { title: string; children: ReactNode; testID?: string }) {
  return (
    <View testID={testID} style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

export function ActionButton({
  title,
  onPress,
  testID,
  tone = 'primary',
  disabled,
}: {
  title: string;
  onPress: () => void;
  testID?: string;
  tone?: 'primary' | 'danger';
  disabled?: boolean;
}) {
  const color = tone === 'danger' ? colors.danger : colors.primary;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={[styles.action, { borderColor: color }, disabled && styles.disabled]}
    >
      <Text style={[styles.actionText, { color }]}>{title}</Text>
    </Pressable>
  );
}

export const adminStyles = StyleSheet.create({
  card: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, gap: 4 },
  cardTitle: { fontSize: 16, fontWeight: '600', color: colors.text, textAlign: 'left' },
  cardLine: { fontSize: 14, color: colors.muted, textAlign: 'left' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  note: { fontSize: 14, color: colors.muted, textAlign: 'left' },
  success: { fontSize: 14, color: colors.success, textAlign: 'left' },
  error: errorTextStyle,
});

const styles = StyleSheet.create({
  section: { gap: 8, marginBottom: 12 },
  sectionTitle: { fontSize: 18, fontWeight: '700', color: colors.text, textAlign: 'left' },
  action: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 6 },
  actionText: { fontSize: 14, fontWeight: '600' },
  disabled: { opacity: 0.4 },
});
