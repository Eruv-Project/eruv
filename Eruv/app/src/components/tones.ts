// Status tones: a bright mark colour (ring, log dots) and a dark tinted ground
// (the status panel), both drawn from the icon's palette.
import { palette } from './ui';

export type BannerTone = 'ok' | 'break' | 'warning' | 'neutral';

export const toneColors: Record<BannerTone, string> = {
  ok: palette.fiber,
  break: palette.breakRed,
  warning: palette.warn,
  neutral: palette.mist,
};

export const bannerColors: Record<BannerTone, string> = {
  ok: '#0E3044',
  break: '#4A1622',
  warning: '#43280F',
  neutral: '#1A2B44',
};
