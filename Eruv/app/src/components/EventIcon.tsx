// A small picture for each kind of log event, so the log reads at a glance without
// reading the text: the control cabinet, a route between two poles, the intact
// ring, the lost connection, the measuring device. Drawn in a 48 x 48 box.
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, G, Line, Path, Rect } from 'react-native-svg';

import { type BannerTone, tintColors, toneColors } from './tones';

export type EventIconName =
  | 'route'
  | 'cabinet'
  | 'brokenRing'
  | 'intact'
  | 'signalOff'
  | 'signalOn'
  | 'tool'
  | 'ruler'
  | 'search'
  | 'chart';

function Pin({ x, y, color }: { x: number; y: number; color: string }) {
  // A map pin whose tip is at (x, y).
  return (
    <G>
      <Path d={`M${x} ${y} C${x - 2} ${y - 5} ${x - 7} ${y - 8} ${x - 7} ${y - 13} a7 7 0 0 1 14 0 C${x + 7} ${y - 8} ${x + 2} ${y - 5} ${x} ${y} Z`} fill={color} />
      <Circle cx={x} cy={y - 13} r={2.8} fill="#FFFFFF" />
    </G>
  );
}

function Picture({ name, color }: { name: EventIconName; color: string }) {
  switch (name) {
    case 'route':
      return (
        <G>
          <Path d="M14 38 C 22 36, 18 28, 26 26 S 32 18, 34 16" stroke="#667085" strokeWidth={2} strokeDasharray="3 3" fill="none" strokeLinecap="round" />
          <Pin x={13} y={40} color={color} />
          <Pin x={35} y={22} color={color} />
        </G>
      );
    case 'cabinet':
      return (
        <G>
          <Rect x={13} y={8} width={24} height={34} rx={2} fill="#C9CED6" stroke="#8C949F" strokeWidth={1.5} />
          <Rect x={17} y={12} width={16} height={26} rx={1} fill="#E9ECF0" stroke="#AEB5BF" strokeWidth={1} />
          <Circle cx={21} cy={18} r={2} fill="#2E9E5B" />
          <Circle cx={27} cy={18} r={2} fill="#2E9E5B" />
          <Circle cx={21} cy={25} r={2} fill={color} />
          <Circle cx={27} cy={25} r={2} fill="#E9A83A" />
          {/* The open door. */}
          <Path d="M13 8 L6 11 L6 39 L13 42 Z" fill="#DDE1E6" stroke="#8C949F" strokeWidth={1.5} strokeLinejoin="round" />
          <Rect x={13} y={42} width={4} height={3} fill="#8C949F" />
          <Rect x={33} y={42} width={4} height={3} fill="#8C949F" />
        </G>
      );
    case 'brokenRing':
      return (
        <G>
          <Path d="M30 9.5 A15 15 0 1 0 39 24" stroke={color} strokeWidth={4} fill="none" strokeLinecap="round" />
          <Path d="M33 12 l3 3 m0 -6 l3 3" stroke={color} strokeWidth={2.5} strokeLinecap="round" />
        </G>
      );
    case 'intact':
      return (
        <G>
          <Circle cx={24} cy={24} r={15} stroke={color} strokeWidth={4} fill="none" />
          <Path d="M17 24.5 l5 5 l9 -10" stroke={color} strokeWidth={3.5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </G>
      );
    case 'signalOff':
    case 'signalOn':
      return (
        <G>
          <Path d="M24 22 L18 40 M24 22 L30 40 M20 34 H28" stroke="#667085" strokeWidth={2.2} strokeLinecap="round" />
          <Circle cx={24} cy={20} r={3} fill={color} />
          <Path d="M17 13 a10 10 0 0 0 0 14 M31 13 a10 10 0 0 1 0 14" stroke={color} strokeWidth={2.5} fill="none" strokeLinecap="round" />
          <Path d="M12 9 a16 16 0 0 0 0 22 M36 9 a16 16 0 0 1 0 22" stroke={color} strokeWidth={2.5} fill="none" strokeLinecap="round" />
          {name === 'signalOff' ? <Line x1={9} y1={41} x2={39} y2={7} stroke={color} strokeWidth={3.5} strokeLinecap="round" /> : null}
        </G>
      );
    case 'tool':
      return (
        <G>
          <Path
            d="M33 9 a8 8 0 0 0 -9 10.5 L10.5 33 a3 3 0 0 0 4.5 4.5 L28.5 24 a8 8 0 0 0 10.5 -9 l-5 5 l-4.5 -1 l-1 -4.5 Z"
            fill={color}
          />
        </G>
      );
    case 'ruler':
      return (
        <G>
          <Rect x={6} y={18} width={36} height={13} rx={2} fill="#FFFFFF" stroke={color} strokeWidth={2.5} />
          <Path d="M12 18 v5 M18 18 v7 M24 18 v5 M30 18 v7 M36 18 v5" stroke={color} strokeWidth={2} strokeLinecap="round" />
        </G>
      );
    case 'search':
      return (
        <G>
          <Circle cx={21} cy={21} r={10} stroke={color} strokeWidth={3.5} fill="none" />
          <Line x1={28.5} y1={28.5} x2={38} y2={38} stroke={color} strokeWidth={4} strokeLinecap="round" />
        </G>
      );
    case 'chart':
      return (
        <G>
          <Path d="M9 9 V39 H40" stroke="#667085" strokeWidth={2.2} fill="none" strokeLinecap="round" />
          <Path d="M13 33 L20 25 L26 29 L37 15" stroke={color} strokeWidth={3} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </G>
      );
  }
}

export function EventIcon({ name, tone, size = 60 }: { name: EventIconName; tone: BannerTone; size?: number }) {
  const tile = tintColors[tone];
  return (
    <View
      testID={`event-icon-${name}`}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.tile, { width: size, height: size, backgroundColor: tile.bg, borderColor: tile.border }]}
    >
      <Svg width={size * 0.8} height={size * 0.8} viewBox="0 0 48 48">
        <Picture name={name} color={toneColors[tone]} />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  tile: { borderRadius: 14, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
});
