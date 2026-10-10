// Launch screen: the app's artwork across the whole screen while the app starts.
//
// The native splash (expo-splash-screen, app.config.ts) is a small icon on the
// night ground; operating systems limit it to that. This view takes over from it:
// the artwork grows from the icon's size to the full width of the screen (its
// edges are the same night colour, so any screen shape looks full), stays until
// the app is ready and has been shown for at least MIN_SHOWN_MS, then fades out.
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Image, StyleSheet, useWindowDimensions } from 'react-native';

import { colors } from './ui';

const ARTWORK = require('../../assets/icon.png');
const MIN_SHOWN_MS = 1400;
const FADE_MS = 380;

export function Splash({ ready, onShown }: { ready: boolean; onShown: () => void }) {
  const { width, height } = useWindowDimensions();
  const size = Math.min(width, height);
  const grow = useRef(new Animated.Value(0)).current;
  const fade = useRef(new Animated.Value(1)).current;
  const [minElapsed, setMinElapsed] = useState(false);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (cancelled) return;
      Animated.timing(grow, {
        toValue: 1,
        duration: reduce ? 0 : 700,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }).start();
    });
    const timer = setTimeout(() => setMinElapsed(true), MIN_SHOWN_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [grow]);

  useEffect(() => {
    if (!ready || !minElapsed) return;
    Animated.timing(fade, { toValue: 0, duration: FADE_MS, useNativeDriver: true }).start(() => setGone(true));
  }, [ready, minElapsed, fade]);

  if (gone) return null;
  return (
    <Animated.View
      testID="splash"
      pointerEvents={ready && minElapsed ? 'none' : 'auto'}
      onLayout={onShown}
      style={[styles.cover, { opacity: fade }]}
    >
      <Animated.View
        style={{
          opacity: grow.interpolate({ inputRange: [0, 0.4, 1], outputRange: [0.6, 1, 1] }),
          transform: [{ scale: grow.interpolate({ inputRange: [0, 1], outputRange: [0.45, 1] }) }],
        }}
      >
        <Image
          source={ARTWORK}
          style={{ width: size, height: size }}
          resizeMode="contain"
          accessibilityLabel="עירוב"
        />
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  cover: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
