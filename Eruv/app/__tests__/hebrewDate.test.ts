import { formatHebrewDate, gematria, hebrewDateAt, hebrewDateOfDay } from '../src/lib/hebrewDate';

describe('gematria', () => {
  it('writes Hebrew numerals with geresh and gershayim', () => {
    expect(gematria(1)).toBe('א׳');
    expect(gematria(10)).toBe('י׳');
    expect(gematria(15)).toBe('ט״ו');
    expect(gematria(16)).toBe('ט״ז');
    expect(gematria(22)).toBe('כ״ב');
    expect(gematria(30)).toBe('ל׳');
    expect(gematria(5787)).toBe('תשפ״ז');
    expect(gematria(5800)).toBe('ת״ת');
  });
});

describe('hebrewDateOfDay', () => {
  // Node's ICU knows the Hebrew calendar: every day over several years must agree.
  const icu = new Intl.DateTimeFormat('en-u-ca-hebrew', { day: 'numeric', month: 'numeric', year: 'numeric', timeZone: 'UTC' });

  it('matches the ICU Hebrew calendar for every day from 2024 to 2032', () => {
    const icuMonths: Record<string, number> = {};
    let mismatches = 0;
    for (let t = Date.UTC(2024, 0, 1); t < Date.UTC(2033, 0, 1); t += 86400000) {
      const d = new Date(t);
      const ours = hebrewDateOfDay(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
      const parts = icu.formatToParts(d);
      const day = Number(parts.find((p) => p.type === 'day')?.value);
      const year = Number(parts.find((p) => p.type === 'year')?.value);
      // ICU numbers months from Tishrei; just require day and year to agree and the
      // month to change exactly when ICU's does.
      const icuMonth = parts.find((p) => p.type === 'month')?.value ?? '';
      const key = `${year}-${icuMonth}`;
      icuMonths[key] ??= ours.month;
      if (ours.day !== day || ours.year !== year || icuMonths[key] !== ours.month) mismatches++;
    }
    expect(mismatches).toBe(0);
  });

  it('knows the dates around Rosh Hashana 5787', () => {
    expect(formatHebrewDate(hebrewDateOfDay(2026, 9, 12))).toBe('א׳ תשרי תשפ״ז');
    expect(formatHebrewDate(hebrewDateOfDay(2026, 10, 3))).toBe('כ״ב תשרי תשפ״ז');
    expect(formatHebrewDate(hebrewDateOfDay(2026, 9, 11))).toBe('כ״ט אלול תשפ״ו');
  });
});

describe('hebrewDateAt', () => {
  it('moves to the next Hebrew day at sunset in Israel', () => {
    // 3 Oct 2026, sunset in Be'er Sheva about 17:30 Israel time (14:30 UTC).
    expect(formatHebrewDate(hebrewDateAt(new Date('2026-10-03T12:00:00Z')))).toBe('כ״ב תשרי תשפ״ז');
    expect(formatHebrewDate(hebrewDateAt(new Date('2026-10-03T19:17:00Z')))).toBe('כ״ג תשרי תשפ״ז');
    // After midnight Israel time it is still the same Hebrew day until sunset.
    expect(formatHebrewDate(hebrewDateAt(new Date('2026-10-03T22:30:00Z')))).toBe('כ״ג תשרי תשפ״ז');
  });
});
