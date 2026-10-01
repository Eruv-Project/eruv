import { readFileSync } from 'fs';
import { join } from 'path';

import { MAP_HTML } from '../src/components/mapHtml.generated';

describe('map page', () => {
  it('the inlined page matches assets/leaflet/map.html (run `npm run build:map`)', () => {
    const source = readFileSync(join(__dirname, '../assets/leaflet/map.html'), 'utf8').replace(/\r\n/g, '\n');
    expect(MAP_HTML).toBe(source);
  });

  it('uses OpenStreetMap tiles with attribution and integrity-checked Leaflet', () => {
    expect(MAP_HTML).toContain('https://tile.openstreetmap.org/{z}/{x}/{y}.png');
    expect(MAP_HTML).toContain('OpenStreetMap</a> contributors');
    expect(MAP_HTML).toMatch(/leaflet\.js"\s+integrity="sha256-/);
    expect(MAP_HTML).toMatch(/leaflet\.css"\s+integrity="sha256-/);
  });
});
