/**
 * The API error type.
 *
 * Lives apart from `client.ts` so error-handling helpers can depend on it
 * without pulling the Supabase client (and therefore react-native) into
 * their module graph.
 */

export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
  }
}
