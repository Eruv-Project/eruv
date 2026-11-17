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
  ok: { bg: '#EFF4FF', border: '#C7D7FE' },
  break: { bg: '#FEF3F2', border: '#FECDCA' },
  warning: { bg: '#FFFAEB', border: '#FEDF89' },
  neutral: { bg: '#F2F4F7', border: '#E4E7EC' },
};

export const bannerColors: Record<BannerTone, string> = {
  ok: '#FFFFFF',
  break: '#FEF3F2',
  warning: '#FFFAEB',
  neutral: '#F2F4F7',
};
