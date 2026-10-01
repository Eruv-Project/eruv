// OpenStreetMap ring map (R15, R17; KTD4): the Leaflet page in a WebView, fed over a
// message bridge. Reusable for any pole list (e.g. an admin pole-import preview):
// pass `breakPoint={null}` to just draw the ring.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

import type { Pole } from '../api/client';
import { apiOrigin } from '../config';
import { he } from '../i18n/he';
import { MAP_HTML } from './mapHtml.generated';

/** Identifies the app to the OpenStreetMap tile servers (tile usage policy). */
export const MAP_USER_AGENT_APP = 'EruvMonitor/1.0';

export interface MapBreakPoint {
  lat: number;
  lon: number;
  /** Bounding pole numbers to highlight and always label (one at the cabinet). */
  poles: number[];
}

export type MapView = 'break' | 'ring';

export interface EruvMapProps {
  poles: Pole[];
  breakPoint?: MapBreakPoint | null;
  testID?: string;
}

/** The bridge message for the page (see assets/leaflet/map.html). */
export function mapMessage(poles: Pole[], breakPoint: MapBreakPoint | null, view: MapView): string {
  return JSON.stringify({ type: 'render', poles, breakPoint, view: breakPoint ? view : 'ring' });
}

export function EruvMap({ poles, breakPoint = null, testID = 'eruv-map' }: EruvMapProps) {
  const webView = useRef<WebView>(null);
  // Bumped on every "ready" from the page, so a reloaded page gets the data again.
  const [readyCount, setReadyCount] = useState(0);
  const [view, setView] = useState<MapView>('break');
  const origin = useMemo(apiOrigin, []);

  const breakKey = breakPoint ? `${breakPoint.lat},${breakPoint.lon}` : '';
  // A new break always opens centred on it (R17).
  useEffect(() => setView('break'), [breakKey]);

  const message = useMemo(() => mapMessage(poles, breakPoint, view), [poles, breakPoint, view]);
  useEffect(() => {
    if (readyCount === 0) return;
    webView.current?.injectJavaScript(`window.eruvReceive(${JSON.stringify(message)}); true;`);
  }, [message, readyCount]);

  const onMessage = useCallback((event: WebViewMessageEvent) => {
    try {
      if (JSON.parse(event.nativeEvent.data)?.type === 'ready') setReadyCount((n) => n + 1);
    } catch {
      // not ours
    }
  }, []);

  return (
    <View style={styles.container} testID={testID}>
      <WebView
        ref={webView}
        source={{ html: MAP_HTML, baseUrl: `${origin}/` }}
        originWhitelist={['*']}
        applicationNameForUserAgent={MAP_USER_AGENT_APP}
        onMessage={onMessage}
        // Links in the page (the OSM attribution) open in the browser, not over the map.
        onShouldStartLoadWithRequest={(request) => {
          const url = request.url;
          if (url.startsWith(origin) || url.startsWith('about:') || url.startsWith('data:')) return true;
          void Linking.openURL(url);
          return false;
        }}
        style={styles.webView}
      />
      {breakPoint ? (
        <Pressable
          testID="map-toggle-view"
          accessibilityRole="button"
          onPress={() => setView((v) => (v === 'break' ? 'ring' : 'break'))}
          style={styles.toggle}
        >
          <Text style={styles.toggleText}>{view === 'break' ? he.city.showRing : he.city.showBreak}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  webView: { flex: 1 },
  toggle: {
    position: 'absolute',
    bottom: 24,
    alignSelf: 'center',
    backgroundColor: '#fff',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    elevation: 3,
    shadowColor: '#000',
    shadowOpacity: 0.2,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  toggleText: { color: '#1f5fa8', fontSize: 15, fontWeight: '600' },
});
