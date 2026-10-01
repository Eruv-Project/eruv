import { fireEvent, render, screen } from '@testing-library/react-native';
import { Linking } from 'react-native';

import type { CityStatus } from '../src/api/client';
import { bannerColors, StatusBanner } from '../src/components/StatusBanner';

// 10:05 UTC is 13:05 in Jerusalem (IDT, UTC+3) on this date.
const NOW = Date.parse('2026-09-30T10:05:00Z');
const ONE_MIN_AGO = '2026-09-30T10:04:00Z';

function status(overrides: Partial<CityStatus> = {}): CityStatus {
  return {
    id: 7,
    name: 'באר שבע',
    line_state: 'OK',
    display_line_state: 'OK',
    device_health: 'ONLINE',
    device_health_since: null,
    last_result_at: ONE_MIN_AGO,
    active_break: null,
    ...overrides,
  };
}

function breakStatus(mapping: Record<string, unknown> | null, overrides: Partial<CityStatus> = {}): CityStatus {
  return status({
    line_state: 'BREAK',
    display_line_state: 'BREAK',
    active_break: { event_id: 12, occurred_at: '2026-09-30T09:00:00Z', replayed: false, mapping: mapping as any },
    ...overrides,
  });
}

const BETWEEN = {
  kind: 'between',
  pole_a: 57,
  pole_b: 58,
  lat: 31.2518,
  lon: 34.7913,
  geo_distance_m: 12400,
  offset_from_a_m: 20,
};
const AT_CABINET = { ...BETWEEN, kind: 'at_cabinet', pole_a: 1, pole_b: null, offset_from_a_m: 0 };
const BEYOND = { ...BETWEEN, kind: 'beyond_ring', pole_a: 120, pole_b: 1 };

async function show(s: CityStatus, serverUnreachable = false) {
  await render(<StatusBanner status={s} now={NOW} serverUnreachable={serverUnreachable} />);
}

function bannerBg() {
  return screen.getByTestId('status-banner');
}

describe('StatusBanner (R16)', () => {
  it('AE7: BREAK + DISCONNECTED stays red with the pole pair and adds an orange line', async () => {
    await show(
      breakStatus(BETWEEN, {
        device_health: 'DISCONNECTED',
        device_health_since: '2026-09-30T09:30:00Z',
        // The device is offline, so the last check is old; the banner must stay red regardless.
        last_result_at: '2026-09-30T09:28:00Z',
      }),
    );
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.break });
    expect(screen.getByTestId('banner-title')).toHaveTextContent('קרע בין עמוד 57 לעמוד 58');
    const secondary = screen.getByTestId('banner-secondary');
    expect(secondary).toHaveTextContent('הניטור מנותק מאז 12:30');
    expect(secondary).toHaveStyle({ backgroundColor: bannerColors.warning });
  });

  it.each([
    ['OK', 'OK', 'ONLINE', 'ok', 'העירוב תקין'],
    ['SUSPECT_BREAK', 'OK', 'ONLINE', 'ok', 'העירוב תקין'],
    ['AWAITING_REFERENCE', 'AWAITING_REFERENCE', 'ONLINE', 'neutral', 'ממתין לבדיקת ייחוס'],
    ['OK', 'OK', 'DISCONNECTED', 'warning', 'ניטור מנותק'],
    ['OK', 'OK', 'FAULT', 'warning', 'תקלת ציוד'],
    ['AWAITING_REFERENCE', 'AWAITING_REFERENCE', 'DISCONNECTED', 'warning', 'ניטור מנותק'],
    ['AWAITING_REFERENCE', 'AWAITING_REFERENCE', 'FAULT', 'warning', 'תקלת ציוד'],
  ] as const)('line %s (shown %s) with device %s is %s "%s"', async (line, display, device, tone, text) => {
    await show(status({ line_state: line, display_line_state: display, device_health: device }));
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors[tone] });
    expect(screen.getByTestId('banner-title')).toHaveTextContent(text);
    expect(screen.queryByTestId('banner-secondary')).toBeNull();
  });

  it('BREAK + ONLINE is red with no secondary line', async () => {
    await show(breakStatus(BETWEEN));
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.break });
    expect(screen.queryByTestId('banner-secondary')).toBeNull();
  });

  it('BREAK + FAULT stays red with an orange equipment-fault line', async () => {
    await show(breakStatus(BETWEEN, { device_health: 'FAULT', device_health_since: '2026-09-30T08:15:00Z' }));
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.break });
    expect(screen.getByTestId('banner-secondary')).toHaveTextContent('תקלת ציוד מאז 11:15');
  });

  it.each([
    ['between', BETWEEN, 'קרע בין עמוד 57 לעמוד 58', 'ניווט ב-Waze'],
    ['at_cabinet', AT_CABINET, 'קרע בארון הבקרה / launch box', 'ניווט ב-Waze'],
    ['beyond_ring', BEYOND, 'קרע מעבר לטבעת הממופה (מיקום משוער)', 'ניווט ב-Waze (משוער)'],
  ])('break variant %s reads correctly and offers Waze', async (_kind, mapping, title, nav) => {
    await show(breakStatus(mapping));
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.break });
    expect(screen.getByTestId('banner-title')).toHaveTextContent(title);
    expect(screen.getByTestId('banner-navigate')).toHaveTextContent(nav);
  });

  it('an unknown mapping reads as a generic break without a navigation link', async () => {
    await show(breakStatus(null));
    expect(screen.getByTestId('banner-title')).toHaveTextContent('קרע בעירוב');
    expect(screen.queryByTestId('banner-navigate')).toBeNull();
  });

  it('the navigation link opens Waze at the break point', async () => {
    const can = jest.spyOn(Linking, 'canOpenURL').mockResolvedValue(true);
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
    await show(breakStatus(BETWEEN));
    await fireEvent.press(screen.getByTestId('banner-navigate'));
    expect(can).toHaveBeenCalledWith('waze://');
    expect(open).toHaveBeenCalledWith('https://waze.com/ul?ll=31.2518,34.7913&navigate=yes');
  });

  it('the info button explains that a second break is invisible', async () => {
    await show(breakStatus(BETWEEN));
    expect(screen.queryByText('ה-OTDR לא יכול לראות קרע נוסף אחרי הקרע הראשון עד שהוא יתוקן')).toBeNull();
    await fireEvent.press(screen.getByTestId('banner-info'));
    expect(screen.getByText('ה-OTDR לא יכול לראות קרע נוסף אחרי הקרע הראשון עד שהוא יתוקן')).toBeTruthy();
  });

  it('shows orange "no contact" with the last known state when the last check is 5 minutes old', async () => {
    await show(status({ last_result_at: '2026-09-30T10:00:00Z' }));
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.warning });
    expect(screen.getByTestId('banner-title')).toHaveTextContent('אין קשר לשרת הניטור');
    expect(screen.getByTestId('banner-secondary')).toHaveTextContent('מצב אחרון ידוע: העירוב תקין');
  });

  it('a last check 2.5 minutes old is still fresh', async () => {
    await show(status({ last_result_at: '2026-09-30T10:02:30Z' }));
    expect(screen.getByTestId('banner-title')).toHaveTextContent('העירוב תקין');
  });

  it('shows "no contact" when the server is unreachable, keeping a known break as the last state', async () => {
    await show(breakStatus(BETWEEN), true);
    expect(bannerBg()).toHaveStyle({ backgroundColor: bannerColors.warning });
    expect(screen.getByTestId('banner-title')).toHaveTextContent('אין קשר לשרת הניטור');
    expect(screen.getByTestId('banner-secondary')).toHaveTextContent('מצב אחרון ידוע: קרע בין עמוד 57 לעמוד 58');
    expect(screen.getByTestId('banner-navigate')).toBeTruthy();
  });

  it('shows the last check in Jerusalem time and relative to now', async () => {
    await show(status({ last_result_at: '2026-09-30T10:03:00Z' }));
    expect(screen.getByTestId('banner-last-check')).toHaveTextContent('בדיקה אחרונה: 13:03 (לפני 2 דקות)');
  });

  it('says so when no check has been received yet', async () => {
    await show(status({ display_line_state: 'AWAITING_REFERENCE', line_state: 'AWAITING_REFERENCE', last_result_at: null }));
    expect(screen.getByTestId('banner-last-check')).toHaveTextContent('טרם התקבלה בדיקה');
  });
});
