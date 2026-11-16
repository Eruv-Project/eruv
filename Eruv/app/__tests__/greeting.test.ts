// Node re-reads TZ when it changes, so local-time dates below are Israel time.
process.env.TZ = 'Asia/Jerusalem';

import { greeting, sunsetUtc } from '../src/lib/greeting';

const at = (iso: string) => new Date(iso);

describe('sunsetUtc', () => {
  it('matches the published Be\'er Sheva sunset within a few minutes', () => {
    // 16 Nov 2026: about 16:43 Israel time (14:43 UTC); 21 Jun: about 19:48 (16:48 UTC).
    const nov = new Date(sunsetUtc(at('2026-11-16T10:00:00Z')));
    expect(Math.abs(nov.getTime() - Date.UTC(2026, 10, 16, 14, 43))).toBeLessThan(5 * 60000);
    const jun = new Date(sunsetUtc(at('2026-06-21T10:00:00Z')));
    expect(Math.abs(jun.getTime() - Date.UTC(2026, 5, 21, 16, 48))).toBeLessThan(5 * 60000);
  });
});

describe('greeting', () => {
  it('greets by the time of day with the first name', () => {
    expect(greeting('עודד לוי', at('2026-11-17T06:30:00+02:00'))).toBe('בוקר טוב עודד');
    expect(greeting('עודד', at('2026-11-17T13:00:00+02:00'))).toBe('צהריים טובים עודד');
    expect(greeting('עודד', at('2026-11-17T19:00:00+02:00'))).toBe('ערב טוב עודד');
    expect(greeting('עודד', at('2026-11-17T02:00:00+02:00'))).toBe('ערב טוב עודד');
  });

  it('says "שבוע טוב" from nightfall on Saturday through the night', () => {
    // Saturday 21 Nov 2026: sunset ~16:40, nightfall ~17:20.
    expect(greeting('עודד', at('2026-11-21T16:00:00+02:00'))).toBe('שבת שלום עודד');
    expect(greeting('עודד', at('2026-11-21T17:00:00+02:00'))).toBe('שבת שלום עודד');
    expect(greeting('עודד', at('2026-11-21T17:30:00+02:00'))).toBe('שבוע טוב עודד');
    expect(greeting('עודד', at('2026-11-22T01:00:00+02:00'))).toBe('שבוע טוב עודד');
    expect(greeting('עודד', at('2026-11-22T08:00:00+02:00'))).toBe('בוקר טוב עודד');
  });

  it('says "שבת שלום" from Friday noon until nightfall on Saturday', () => {
    expect(greeting('עודד', at('2026-11-20T11:30:00+02:00'))).toBe('בוקר טוב עודד');
    expect(greeting('עודד', at('2026-11-20T12:00:00+02:00'))).toBe('שבת שלום עודד');
    expect(greeting('עודד', at('2026-11-20T22:00:00+02:00'))).toBe('שבת שלום עודד');
    expect(greeting('עודד', at('2026-11-21T09:00:00+02:00'))).toBe('שבת שלום עודד');
  });

  it('greets without a name when there is none', () => {
    expect(greeting('  ', at('2026-11-17T06:30:00+02:00'))).toBe('בוקר טוב');
    expect(greeting(undefined, at('2026-11-17T06:30:00+02:00'))).toBe('בוקר טוב');
  });
});
