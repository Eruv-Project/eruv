// Navigation look: the dark theme and the shared header options.
import { DarkTheme, type Theme } from '@react-navigation/native';

import { colors, fonts, palette } from '../components/ui';

export const theme: Theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: colors.primary,
    background: colors.background,
    card: colors.surface,
    text: colors.text,
    border: colors.border,
    notification: palette.breakRed,
  },
};

/** Header look shared by every stack and tab (also used by the admin stack). */
export const headerOptions = {
  headerTitleAlign: 'center' as const,
  headerStyle: { backgroundColor: colors.surface },
  headerTintColor: colors.text,
  headerTitleStyle: { fontFamily: fonts.display, fontSize: 21 },
  headerShadowVisible: false,
};
