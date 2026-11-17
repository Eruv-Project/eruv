// Design tokens and small shared building blocks.
//
// Light theme, clean and modern: a near-white grey ground, white cards, neutral
// greys for text and lines, one bright blue for the header bar, titles and actions,
// gold for the eruv's poles.
// The icon's night navy stays only on the splash. Red and orange appear only for
// a break and for monitoring problems, so they always mean something.
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, type TextInputProps } from 'react-native';

export const palette = {
  /** The icon's ground: the splash only. */
  night: '#0C182A',
  page: '#F6F7F9',
  card: '#FFFFFF',
  rule: '#E4E7EC',
  blue: '#2563EB',
  fiber: '#2563EB',
  gold: '#F2B33D',
  ink: '#101828',
  mist: '#667085',
  breakRed: '#D92D20',
  warn: '#B54708',
};

export const colors = {
  primary: palette.blue,
  /** Text on a primary-coloured fill. */
  onPrimary: '#FFFFFF',
  text: palette.ink,
  muted: palette.mist,
  danger: palette.breakRed,
  warningBg: '#FEF3F2',
  border: palette.rule,
  selected: '#EFF4FF',
  success: '#067647',
  background: palette.page,
  surface: palette.card,
  gold: palette.gold,
  /** The header bar behind the screen titles and the status bar. */
  bar: palette.blue,
  onBar: '#FFFFFF',
};

/** Rubik: a clean, modern Hebrew sans for all text (loaded in App.tsx). Each weight
 * is its own family, so styles pick a family instead of setting fontWeight. */
export const fonts = {
  regular: 'Rubik_400Regular',
  medium: 'Rubik_500Medium',
  semibold: 'Rubik_600SemiBold',
  bold: 'Rubik_700Bold',
  /** Screen and card titles. */
  display: 'Rubik_700Bold',
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
  body: { fontFamily: fonts.regular, fontSize: 16, color: colors.text, lineHeight: 24, textAlign: 'left' },
  error: { fontFamily: fonts.regular, fontSize: 14, lineHeight: 20, color: colors.danger, textAlign: 'left' },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontFamily: fonts.regular,
    fontSize: 16,
    textAlign: 'right',
    color: colors.text,
  },
  button: { backgroundColor: colors.primary, borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
  buttonText: { color: colors.onPrimary, fontSize: 16, fontFamily: fonts.bold },
  link: { paddingVertical: 10, alignItems: 'center' },
  linkText: { color: colors.primary, fontSize: 15, fontFamily: fonts.semibold },
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
  chipText: { fontFamily: fonts.regular, color: colors.text },
  chipTextActive: { color: colors.onPrimary, fontFamily: fonts.bold },
});

/** Shared small error-text style (also used by the admin screens). */
export const errorTextStyle = styles.error;
