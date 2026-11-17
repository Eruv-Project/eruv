// The greeting above the city ("בוקר טוב עודד"), by the phone's clock. From Friday
// noon until nightfall on Saturday it is "שבת שלום"; on Motzaei Shabbat (Saturday
// after nightfall, through the night) it is "שבוע טוב".
import { he } from '../i18n/he';
import { sunsetUtc } from './sun';

export { sunsetUtc };

/** Nightfall used for the end of Shabbat: sunset plus this many minutes. */
const NIGHTFALL_AFTER_SUNSET_MIN = 40;

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
