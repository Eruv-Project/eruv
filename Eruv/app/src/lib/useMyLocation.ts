// The phone's own position for the City map: where the maintainer is, next to
// the eruv ring and a break. Foreground only, and only while the caller is
// active (the City tab is focused), so it costs no battery in the background.
import * as Location from 'expo-location';
import { useEffect, useState } from 'react';

export interface MyLocation {
  lat: number;
  lon: number;
  /** Radius of the 68% confidence circle, metres. */
  accuracy: number | null;
}

export type LocationPermission = 'unknown' | 'granted' | 'denied';

export function useMyLocation(active: boolean): { location: MyLocation | null; permission: LocationPermission } {
  const [location, setLocation] = useState<MyLocation | null>(null);
  const [permission, setPermission] = useState<LocationPermission>('unknown');

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let sub: Location.LocationSubscription | null = null;
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (cancelled) return;
        if (status !== 'granted') {
          setPermission('denied');
          return;
        }
        setPermission('granted');
        sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, distanceInterval: 5, timeInterval: 5000 },
          (pos) =>
            setLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy ?? null }),
        );
        if (cancelled) sub.remove();
      } catch {
        // Location services off or unavailable: the map simply shows no dot.
        if (!cancelled) setPermission('denied');
      }
    })();
    return () => {
      cancelled = true;
      sub?.remove();
    };
  }, [active]);

  return { location, permission };
}
