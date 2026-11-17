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

/** Light tints for a tone's picture tile and its sentence pill in the log. */
export const tintColors: Record<BannerTone, { bg: string; border: string }> = {
  ok: { bg: '#E8F0FC', border: '#BFD3F2' },
  break: { bg: '#FDECEC', border: '#F2C4C4' },
  warning: { bg: '#FDF1E3', border: '#F1D2AE' },
  neutral: { bg: '#EEF1F6', border: '#D5DCE8' },
};

export const bannerColors: Record<BannerTone, string> = {
  ok: '#FFFFFF',
  break: '#FDECEC',
  warning: '#FDF1E3',
  neutral: '#EEF1F6',
};
