// Sunset in Israel, for the greeting ("שבוע טוב" after Shabbat) and the Hebrew date,
// which starts at sunset. Be'er Sheva; sunset differs by only a few minutes across
// the country.
const LAT = 31.25;
const LON = 34.79;

const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;
const mod = (x: number, m: number) => ((x % m) + m) % m;

/** Sunset (official zenith 90.833°) on `date`'s UTC calendar day, as a timestamp. */
export function sunsetUtc(date: Date, lat = LAT, lon = LON): number {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const dayStart = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  const n = Math.round((dayStart - start) / 86400000);
  const lngHour = lon / 15;
  const t = n + (18 - lngHour) / 24;
  const m = 0.9856 * t - 3.289;
  const l = mod(m + 1.916 * Math.sin(rad(m)) + 0.02 * Math.sin(rad(2 * m)) + 282.634, 360);
  let ra = mod(deg(Math.atan(0.91764 * Math.tan(rad(l)))), 360);
  ra = (ra + Math.floor(l / 90) * 90 - Math.floor(ra / 90) * 90) / 15;
  const sinDec = 0.39782 * Math.sin(rad(l));
  const cosDec = Math.cos(Math.asin(sinDec));
  const cosH = (Math.cos(rad(90.833)) - sinDec * Math.sin(rad(lat))) / (cosDec * Math.cos(rad(lat)));
  const h = deg(Math.acos(cosH)) / 15;
  const ut = mod(h + ra - 0.06571 * t - 6.622 - lngHour, 24);
  return dayStart + ut * 3600000;
}
