// Number display for distances and dB values: grouped thousands, at most one decimal.
const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

export function formatNumber(value: number): string {
  return numberFormat.format(value);
}
