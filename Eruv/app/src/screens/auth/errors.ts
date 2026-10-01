import { ApiError } from '../../api/client';
import { he } from '../../i18n/he';

/** Hebrew message for a failed auth request; `byStatus` overrides per HTTP status. */
export function authErrorMessage(err: unknown, byStatus: Record<number, string> = {}): string {
  if (!(err instanceof ApiError)) return he.common.networkError;
  if (byStatus[err.status]) return byStatus[err.status];
  if (err.status === 429) return he.common.rateLimited;
  return he.common.genericError;
}
