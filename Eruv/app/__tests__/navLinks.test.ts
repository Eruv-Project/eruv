import { googleMapsUrl, openNavigation, wazeUrl } from '../src/lib/navLinks';

const LAT = 31.2518;
const LON = 34.7913;
const WAZE = 'https://waze.com/ul?ll=31.2518,34.7913&navigate=yes';
const GOOGLE = 'https://www.google.com/maps/dir/?api=1&destination=31.2518,34.7913';

function fakeLinking(canOpen: boolean | Error) {
  return {
    canOpenURL: jest.fn(async (_url: string) => {
      if (canOpen instanceof Error) throw canOpen;
      return canOpen;
    }),
    openURL: jest.fn(async (_url: string) => undefined),
  };
}

describe('navigation links (R17)', () => {
  it('builds the waze.com/ul URL with navigate=yes', () => {
    expect(wazeUrl(LAT, LON)).toBe(WAZE);
  });

  it('builds the Google Maps directions URL', () => {
    expect(googleMapsUrl(LAT, LON)).toBe(GOOGLE);
  });

  it('opens Waze when the Waze app is installed', async () => {
    const linking = fakeLinking(true);
    await openNavigation(LAT, LON, linking);
    expect(linking.canOpenURL).toHaveBeenCalledWith('waze://');
    expect(linking.openURL).toHaveBeenCalledTimes(1);
    expect(linking.openURL).toHaveBeenCalledWith(WAZE);
  });

  it('falls back to Google Maps when Waze is not installed', async () => {
    const linking = fakeLinking(false);
    await openNavigation(LAT, LON, linking);
    expect(linking.openURL).toHaveBeenCalledTimes(1);
    expect(linking.openURL).toHaveBeenCalledWith(GOOGLE);
  });

  it('falls back to Google Maps when the Waze check itself fails', async () => {
    const linking = fakeLinking(new Error('scheme not declared'));
    await openNavigation(LAT, LON, linking);
    expect(linking.openURL).toHaveBeenCalledWith(GOOGLE);
  });
});
