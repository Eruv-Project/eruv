// The city's status drawn as its eruv: a closed ring. Intact is a whole, glowing
// fiber-cyan ring; a break opens a gap in it; monitoring trouble (no contact,
// disconnected, fault) dots it in orange; awaiting the reference dashes it grey.
import Svg, { Circle } from 'react-native-svg';

import { type BannerTone, toneColors } from './tones';

const STROKE = 7;

export function StatusRing({ tone, size = 84 }: { tone: BannerTone; size?: number }) {
  const r = (size - STROKE * 3) / 2;
  const c = size / 2;
  const circumference = 2 * Math.PI * r;
  const color = toneColors[tone];

  let dash: string | undefined;
  if (tone === 'break') dash = `${circumference * 0.82} ${circumference * 0.18}`;
  else if (tone === 'warning') dash = `0.1 ${circumference / 14}`;
  else if (tone === 'neutral') dash = `${circumference / 16} ${circumference / 24}`;

  return (
    <Svg width={size} height={size} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {/* Glow under an intact ring, the icon's lit fiber. */}
      {tone === 'ok' ? <Circle cx={c} cy={c} r={r} stroke={color} strokeOpacity={0.22} strokeWidth={STROKE * 2.6} fill="none" /> : null}
      <Circle
        cx={c}
        cy={c}
        r={r}
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeDasharray={dash}
        // Start the dash pattern at the top, so a break's gap opens at 12 o'clock.
        transform={`rotate(${tone === 'break' ? -90 + 0.09 * 360 : -90} ${c} ${c})`}
        fill="none"
      />
    </Svg>
  );
}
