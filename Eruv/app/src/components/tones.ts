// Status tones: a strong mark colour (ring, log dots, titles) and a light tinted
// ground (the status panel).
import { palette } from './ui';

export type BannerTone = 'ok' | 'break' | 'warning' | 'neutral';

export const toneColors: Record<BannerTone, string> = {
  ok: palette.fiber,
  break: palette.breakRed,
  warning: palette.warn,
  neutral: palette.mist,
};

export const bannerColors: Record<BannerTone, string> = {
  ok: '#FFFFFF',
  break: '#FDECEC',
  warning: '#FDF1E3',
  neutral: '#EEF1F6',
};
