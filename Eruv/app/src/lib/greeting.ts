// The greeting above the city ("בוקר טוב עודד"), by the phone's clock. From Friday
// noon until nightfall on Saturday it is "שבת שלום"; on Motzaei Shabbat (Saturday
// after nightfall, through the night) it is "שבוע טוב".
import { he } from '../i18n/he';

/** Nightfall used for the end of Shabbat: sunset plus this many minutes. */
const NIGHTFALL_AFTER_SUNSET_MIN = 40;
/** Israel (Be'er Sheva); sunset differs by only a few minutes across the country. */
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

function afterNightfall(now: Date): boolean {
  return now.getTime() >= sunsetUtc(now) + NIGHTFALL_AFTER_SUNSET_MIN * 60000;
}

function isShabbat(now: Date): boolean {
  const day = now.getDay();
  return (day === 5 && now.getHours() >= 12) || (day === 6 && !afterNightfall(now));
}

function isMotzaeiShabbat(now: Date): boolean {
  const day = now.getDay();
  return (day === 6 && afterNightfall(now)) || (day === 0 && now.getHours() < 5);
}

/** "בוקר טוב עודד": the first word of the user's name, or the greeting alone. */
export function greeting(name: string | null | undefined, now: Date): string {
  const hour = now.getHours();
  let text: string;
  if (isShabbat(now)) text = he.greeting.shabbat;
  else if (isMotzaeiShabbat(now)) text = he.greeting.goodWeek;
  else if (hour >= 5 && hour < 12) text = he.greeting.morning;
  else if (hour >= 12 && hour < 17) text = he.greeting.noon;
  else text = he.greeting.evening;
  const first = name?.trim().split(/\s+/)[0];
  return first ? `${text} ${first}` : text;
}
