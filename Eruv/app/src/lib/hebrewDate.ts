// The Hebrew date of a moment, as shown in the log: "כ״ב תשרי תשפ״ז". Computed here
// (the arithmetic Hebrew calendar of Dershowitz & Reingold, "Calendrical
// Calculations") rather than through Intl, whose Hebrew calendar support varies on
// phones. The Hebrew day starts at sunset, so an evening event shows the next date.
import { sunsetUtc } from './sun';

/** R.D. (fixed day number, 1 = 1 Jan of year 1) of the Hebrew calendar's epoch. */
const HEBREW_EPOCH = -1373427;
/** R.D. of 1 Jan 1970. */
const RD_UNIX_EPOCH = 719163;

const NISAN = 1;
const TISHREI = 7;

const isLeapYear = (year: number) => (7 * year + 1) % 19 < 7;
const lastMonthOfYear = (year: number) => (isLeapYear(year) ? 13 : 12);

function elapsedDays(year: number): number {
  const monthsElapsed = Math.floor((235 * year - 234) / 19);
  const partsElapsed = 12084 + 13753 * monthsElapsed;
  const day = 29 * monthsElapsed + Math.floor(partsElapsed / 25920);
  return (3 * (day + 1)) % 7 < 3 ? day + 1 : day;
}

function yearLengthCorrection(year: number): number {
  const ny0 = elapsedDays(year - 1);
  const ny1 = elapsedDays(year);
  const ny2 = elapsedDays(year + 1);
  if (ny2 - ny1 === 356) return 2;
  if (ny1 - ny0 === 382) return 1;
  return 0;
}

const newYear = (year: number) => HEBREW_EPOCH + elapsedDays(year) + yearLengthCorrection(year);
const daysInYear = (year: number) => newYear(year + 1) - newYear(year);

function lastDayOfMonth(month: number, year: number): number {
  if ([2, 4, 6, 10, 13].includes(month)) return 29;
  if (month === 12 && !isLeapYear(year)) return 29;
  if (month === 8 && daysInYear(year) % 10 !== 5) return 29; // Marheshvan, unless long
  if (month === 9 && daysInYear(year) % 10 === 3) return 29; // Kislev, when short
  return 30;
}

function fixedFromHebrew(year: number, month: number, day: number): number {
  let days = newYear(year) + day - 1;
  if (month < TISHREI) {
    for (let m = TISHREI; m <= lastMonthOfYear(year); m++) days += lastDayOfMonth(m, year);
    for (let m = NISAN; m < month; m++) days += lastDayOfMonth(m, year);
  } else {
    for (let m = TISHREI; m < month; m++) days += lastDayOfMonth(m, year);
  }
  return days;
}

export interface HebrewDate {
  year: number;
  /** 1 = Nisan ... 7 = Tishrei ... 12 = Adar (Adar I in a leap year), 13 = Adar II. */
  month: number;
  day: number;
}

function hebrewFromFixed(date: number): HebrewDate {
  const approx = Math.floor((date - HEBREW_EPOCH) / (35975351 / 98496)) + 1;
  // The latest year from approx - 1 on whose new year falls on or before the date.
  let year = approx - 1;
  while (newYear(year + 1) <= date) year++;
  let month = date < fixedFromHebrew(year, NISAN, 1) ? TISHREI : NISAN;
  while (date > fixedFromHebrew(year, month, lastDayOfMonth(month, year))) month++;
  return { year, month, day: date - fixedFromHebrew(year, month, 1) + 1 };
}

/** The Hebrew date of a Gregorian calendar day (no sunset rule). */
export function hebrewDateOfDay(year: number, month: number, day: number): HebrewDate {
  return hebrewFromFixed(RD_UNIX_EPOCH + Math.round(Date.UTC(year, month - 1, day) / 86400000));
}

const israelDay = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jerusalem',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** The Hebrew date at a moment in Israel; from sunset on, it is already the next day. */
export function hebrewDateAt(moment: Date): HebrewDate {
  const parts = israelDay.formatToParts(moment);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const [y, m, d] = [get('year'), get('month'), get('day')];
  const afterSunset = moment.getTime() >= sunsetUtc(new Date(Date.UTC(y, m - 1, d, 12)));
  const civil = new Date(Date.UTC(y, m - 1, d + (afterSunset ? 1 : 0)));
  return hebrewDateOfDay(civil.getUTCFullYear(), civil.getUTCMonth() + 1, civil.getUTCDate());
}

const ONES = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט'];
const TENS = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ'];
const HUNDREDS = ['', 'ק', 'ר', 'ש', 'ת'];

/** Hebrew numerals with geresh / gershayim: 1 → א׳, 15 → ט״ו, 787 → תשפ״ז. */
export function gematria(n: number): string {
  let letters = '';
  let rest = n % 1000;
  while (rest >= 400) {
    letters += 'ת';
    rest -= 400;
  }
  letters += HUNDREDS[Math.floor(rest / 100)];
  rest %= 100;
  if (rest === 15) letters += 'טו';
  else if (rest === 16) letters += 'טז';
  else letters += TENS[Math.floor(rest / 10)] + ONES[rest % 10];
  return letters.length === 1 ? `${letters}׳` : `${letters.slice(0, -1)}״${letters.slice(-1)}`;
}

const MONTHS = ['', 'ניסן', 'אייר', 'סיוון', 'תמוז', 'אב', 'אלול', 'תשרי', 'חשוון', 'כסלו', 'טבת', 'שבט', 'אדר', 'אדר ב׳'];

export function hebrewMonthName(month: number, year: number): string {
  if (month === 12 && isLeapYear(year)) return 'אדר א׳';
  return MONTHS[month];
}

/** "כ״ב תשרי תשפ״ז". */
export function formatHebrewDate(date: HebrewDate): string {
  return `${gematria(date.day)} ${hebrewMonthName(date.month, date.year)} ${gematria(date.year)}`;
}
