// Times shown to maintainers: Israel wall-clock time and a Hebrew "time ago".
import { he } from '../i18n/he';

const clockFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jerusalem',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** "HH:MM" in Asia/Jerusalem. */
export function formatClock(iso: string): string {
  const parts = clockFormat.formatToParts(new Date(iso));
  const hour = parts.find((p) => p.type === 'hour')?.value ?? '00';
  const minute = parts.find((p) => p.type === 'minute')?.value ?? '00';
  return `${hour === '24' ? '00' : hour}:${minute}`;
}

/** "לפני 2 דקות" and friends. A timestamp slightly in the future counts as now. */
export function formatRelative(iso: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  if (minutes < 1) return he.relative.now;
  if (minutes === 1) return he.relative.minute;
  if (minutes < 60) return he.relative.minutes(minutes);
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return he.relative.hour;
  if (hours === 2) return he.relative.twoHours;
  if (hours < 24) return he.relative.hours(hours);
  const days = Math.floor(hours / 24);
  if (days === 1) return he.relative.day;
  if (days === 2) return he.relative.twoDays;
  return he.relative.days(days);
}

const dateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jerusalem',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

/** "DD/MM/YYYY HH:MM" in Asia/Jerusalem, for log rows and admin details. */
export function formatDateTime(iso: string): string {
  return `${dateFormat.format(new Date(iso))} ${formatClock(iso)}`;
}
