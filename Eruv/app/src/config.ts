// The only source of the API base URL (README: "Where to put the AWS address").
export function apiBaseUrl(): string {
  const url = process.env.EXPO_PUBLIC_API_URL;
  if (!url) {
    throw new Error('EXPO_PUBLIC_API_URL is not set; copy app/.env.example to app/.env');
  }
  return url.replace(/\/+$/, '');
}

/** scheme://host[:port] of the API; the map page is loaded under it so tile requests carry a Referer. */
export function apiOrigin(): string {
  const match = /^https?:\/\/[^/]+/i.exec(apiBaseUrl());
  if (!match) throw new Error('EXPO_PUBLIC_API_URL must start with http:// or https://');
  return match[0];
}
