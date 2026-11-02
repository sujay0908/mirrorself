/**
 * Development diagnostics for API failures.
 *
 * Deliberately narrow. Only the transport-level SHAPE of a failure is ever
 * described, logged or rendered: a fixed-vocabulary kind plus the HTTP status.
 * Never a token, an Authorization header, a request body, a response body, or
 * any user content. `APIError.message` is server-supplied and can echo user
 * input, so it is never read here.
 */

import { APIError } from './errors';

export type ApiFailureKind =
  | 'unreachable'
  | 'timeout'
  | 'unauthorized'
  | 'not_found'
  | 'server_error'
  | 'client_error'
  | 'unknown';

export interface ApiFailure {
  kind: ApiFailureKind;
  /** HTTP status, or null when the request never got a response. */
  status: number | null;
  /** Fixed-vocabulary summary. Safe to log and to show. */
  detail: string;
}

function isAbort(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name?: unknown }).name === 'AbortError'
  );
}

export function describeApiFailure(err: unknown): ApiFailure {
  if (err instanceof APIError) {
    const { status } = err;
    if (status === 408) return { kind: 'timeout', status, detail: 'request timed out' };
    if (status === 401 || status === 403) {
      return { kind: 'unauthorized', status, detail: `rejected the session (HTTP ${status})` };
    }
    if (status === 404) return { kind: 'not_found', status, detail: 'HTTP 404' };
    if (status >= 500) return { kind: 'server_error', status, detail: `HTTP ${status}` };
    return { kind: 'client_error', status, detail: `HTTP ${status}` };
  }
  if (isAbort(err)) return { kind: 'timeout', status: null, detail: 'request timed out' };
  // A rejected fetch (connection refused, DNS, CORS preflight) lands here.
  if (err instanceof TypeError) {
    return { kind: 'unreachable', status: null, detail: 'no response from the server' };
  }
  return { kind: 'unknown', status: null, detail: 'unexpected failure' };
}

/** A short, user-visible explanation. `apiUrl` is public build config. */
export function apiFailureMessage(
  failure: ApiFailure | null,
  apiUrl: string,
): string {
  if (!failure) return 'Something went wrong talking to the API.';
  switch (failure.kind) {
    case 'unreachable':
      return `Can't reach the API at ${apiUrl}. Is the backend running?`;
    case 'timeout':
      return `The API at ${apiUrl} did not respond in time.`;
    case 'unauthorized':
      return `The API rejected this session (HTTP ${failure.status ?? 401}). Its JWT verification settings and the Supabase project that issued the token have to match.`;
    case 'server_error':
      return `The API returned HTTP ${failure.status ?? 500}. Check the backend logs.`;
    default:
      return `The API returned ${failure.detail}.`;
  }
}

/**
 * Dev-only breadcrumb. No-ops in release builds. Prints the fixed-vocabulary
 * summary above and nothing else - no tokens, headers or payloads.
 */
export function logApiFailure(scope: string, err: unknown): ApiFailure {
  const failure = describeApiFailure(err);
  if (typeof __DEV__ !== 'undefined' && __DEV__) {
    // eslint-disable-next-line no-console
    console.warn(`[api] ${scope}: ${failure.detail}`);
  }
  return failure;
}
