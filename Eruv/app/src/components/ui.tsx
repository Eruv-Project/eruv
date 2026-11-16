// Design tokens and small shared building blocks.
//
// Light theme, "blue with a coloured bar": a soft blue-white ground, white cards,
// royal blue for the header bar, titles and actions, gold for the eruv's poles.
// The icon's night navy stays only on the splash. Red and orange appear only for
// a break and for monitoring problems, so they always mean something.
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, type TextInputProps } from 'react-native';

export const palette = {
  /** The icon's ground: the splash only. */
  night: '#0C182A',
  page: '#F0F3F9',
  card: '#FFFFFF',
  rule: '#D5DCE8',
  blue: '#1D4E9E',
  fiber: '#2563C4',
  gold: '#E9A83A',
  ink: '#141C2E',
  mist: '#5A616F',
  breakRed: '#C93636',
  warn: '#B45F0E',
};

export const colors = {
  primary: palette.blue,
  /** Text on a primary-coloured fill. */
  onPrimary: '#FFFFFF',
  text: palette.ink,
  muted: palette.mist,
  danger: palette.breakRed,
  warningBg: '#FDECEC',
  border: palette.rule,
  selected: '#DCE6F7',
  success: '#1E7A50',
  background: palette.page,
  surface: palette.card,
  gold: palette.gold,
  /** The header bar behind the screen titles and the status bar. */
  bar: palette.blue,
  onBar: '#FFFFFF',
};

/** Frank Ruhl Libre: a traditional Hebrew serif for headlines (loaded in App.tsx). */
export const fonts = {
  display: 'FrankRuhlLibre_700Bold',
  displayBlack: 'FrankRuhlLibre_900Black',
};

export function Screen({ children }: { children: ReactNode }) {
  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.screen}
      keyboardShouldPersistTaps="handled"
    >
      {children}
    </ScrollView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <Text style={styles.title}>{children}</Text>;
}

export function Body({ children }: { children: ReactNode }) {
  return <Text style={styles.body}>{children}</Text>;
}

export function ErrorText({ children }: { children: ReactNode }) {
  return children ? <Text style={styles.error}>{children}</Text> : null;
}

export function Chip({
  label,
  active,
  onPress,
  testID,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
  testID: string;
}) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

export function Field(props: TextInputProps) {
  return (
    <TextInput
      placeholderTextColor={colors.muted}
      selectionColor={colors.primary}
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function Button({
  title,
  onPress,
  busy,
  variant = 'primary',
  testID,
}: {
  title: string;
  onPress: () => void;
  busy?: boolean;
  variant?: 'primary' | 'link';
  testID?: string;
}) {
  const primary = variant === 'primary';
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      disabled={busy}
      onPress={onPress}
      style={({ pressed }) => [primary ? styles.button : styles.link, pressed && styles.pressed]}
    >
      {busy ? (
        <ActivityIndicator color={primary ? colors.onPrimary : colors.primary} />
      ) : (
        <Text style={primary ? styles.buttonText : styles.linkText}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  scroll: { backgroundColor: colors.background },
  screen: { padding: 24, gap: 14, flexGrow: 1 },
  title: { fontFamily: fonts.display, fontSize: 28, lineHeight: 36, color: colors.text, textAlign: 'left' },
  body: { fontSize: 16, color: colors.text, lineHeight: 24, textAlign: 'left' },
  error: { fontSize: 14, lineHeight: 20, color: colors.danger, textAlign: 'left' },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    textAlign: 'right',
    color: colors.text,
  },
  button: { backgroundColor: colors.primary, borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
  buttonText: { color: colors.onPrimary, fontSize: 16, fontWeight: '700' },
  link: { paddingVertical: 10, alignItems: 'center' },
  linkText: { color: colors.primary, fontSize: 15, fontWeight: '600' },
  pressed: { opacity: 0.75 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.text },
  chipTextActive: { color: colors.onPrimary, fontWeight: '700' },
});

/** Shared small error-text style (also used by the admin screens). */
export const errorTextStyle = styles.error;
