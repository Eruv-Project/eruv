// Navigation to a break point (R17): Waze when the app is installed, else Google Maps.
import { Linking } from 'react-native';

export function wazeUrl(lat: number, lon: number): string {
  return `https://waze.com/ul?ll=${lat},${lon}&navigate=yes`;
}

export function googleMapsUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
}

type LinkOpener = Pick<typeof Linking, 'canOpenURL' | 'openURL'>;

/** Detects Waze by its `waze://` scheme (declared in app.config.ts for iOS and Android 11+),
 *  since an https URL is always "openable". Returns the URL that was opened. */
export async function openNavigation(lat: number, lon: number, linking: LinkOpener = Linking): Promise<string> {
  let hasWaze = false;
  try {
    hasWaze = await linking.canOpenURL('waze://');
  } catch {
    hasWaze = false;
  }
  const url = hasWaze ? wazeUrl(lat, lon) : googleMapsUrl(lat, lon);
  await linking.openURL(url);
  return url;
}
