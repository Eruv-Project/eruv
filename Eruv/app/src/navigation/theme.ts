// Navigation look: the light theme and the shared header options (a solid blue bar).
import { DefaultTheme, type Theme } from '@react-navigation/native';

import { colors, fonts, palette } from '../components/ui';

export const theme: Theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
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
  headerStyle: { backgroundColor: colors.bar },
  headerTintColor: colors.onBar,
  headerTitleStyle: { fontFamily: fonts.display, fontSize: 21 },
  headerShadowVisible: false,
};
