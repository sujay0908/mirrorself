/**
 * The pieces of the chat send path that decide whether a retry can
 * duplicate a message, and what the person is told when a send fails.
 */

import { APIError } from '@/api/errors';
import { keyForSend, newIdempotencyKey } from '@/lib/idempotency';
import { isRetryable, retryAfterSeconds, userErrorMessage } from '@/lib/user-errors';

describe('idempotency keys', () => {
  it('match the format the API accepts', () => {
    for (let i = 0; i < 200; i += 1) {
      const key = newIdempotencyKey();
      expect(key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    }
  });

  it('are different every time', () => {
    const keys = new Set(Array.from({ length: 500 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(500);
  });

  it('reuse the key when the same draft is retried', () => {
    const first = keyForSend(null, 'hello', () => 'key-one-0001');
    const retry = keyForSend(first, 'hello', () => 'key-two-0002');
    expect(retry.key).toBe('key-one-0001');
  });

  it('mint a new key once the text changes', () => {
    const first = keyForSend(null, 'hello', () => 'key-one-0001');
    const edited = keyForSend(first, 'hello there', () => 'key-two-0002');
    expect(edited.key).toBe('key-two-0002');
  });

  it('mint a new key for a new message after a successful one', () => {
    // The screen clears the pending send on success, so the next send starts
    // from null even if the person types the same words again.
    const next = keyForSend(null, 'hello', () => 'key-three-003');
    expect(next.key).toBe('key-three-003');
  });
});

describe('what a person is told when a send fails', () => {
  it('explains a missing AI configuration without blaming the person', () => {
    const err = new APIError(503, 'llm_provider_not_configured', 'ANTHROPIC_API_KEY is not set');
    const text = userErrorMessage(err);
    expect(text).toMatch(/hasn't been set up/);
    expect(text).toMatch(/not sent/);
    // Server text is for developers; never shown.
    expect(text).not.toContain('ANTHROPIC_API_KEY');
  });

  it('never repeats the server message, which can echo user input', () => {
    const echoed = 'my secret diary entry';
    const err = new APIError(400, 'something_new', echoed);
    expect(userErrorMessage(err)).not.toContain(echoed);
  });

  it.each([
    [429, 'rate_limited', /too fast|bit fast/i],
    [409, 'message_in_progress', /still working/i],
    [504, 'llm_timeout', /too long/i],
    [422, 'llm_refused', /declined/i],
    [401, 'unauthorized', /sign in again/i],
    [503, 'database_unavailable', /try again/i],
    [500, 'internal_error', /HTTP 500/],
  ])('HTTP %i %s', (status, code, pattern) => {
    expect(userErrorMessage(new APIError(status, code, 'x'))).toMatch(pattern);
  });

  it('explains a network failure', () => {
    expect(userErrorMessage(new TypeError('Failed to fetch'))).toMatch(/can't reach/i);
  });

  it('explains a client-side timeout', () => {
    expect(userErrorMessage(new APIError(408, 'timeout', 'x'))).toMatch(/in time/i);
  });

  it('has something to say about anything else', () => {
    expect(userErrorMessage('boom')).toBeTruthy();
    expect(userErrorMessage(undefined)).toBeTruthy();
  });
});

describe('which failures are worth a retry button', () => {
  it.each([
    [408, 'timeout', true],
    [409, 'message_in_progress', true],
    [429, 'rate_limited', true],
    [503, 'llm_unavailable', true],
    [504, 'llm_timeout', true],
    [500, 'internal_error', true],
    // Retrying cannot fix configuration or a rejected message.
    [503, 'llm_provider_not_configured', false],
    [503, 'llm_provider_misconfigured', false],
    [422, 'validation_error', false],
    [422, 'llm_refused', false],
    [404, 'conversation_not_found', false],
  ])('HTTP %i %s -> %s', (status, code, expected) => {
    expect(isRetryable(new APIError(status, code, 'x'))).toBe(expected);
  });

  it('retries network failures', () => {
    expect(isRetryable(new TypeError('Failed to fetch'))).toBe(true);
  });

  it('reads the wait the server asked for', () => {
    expect(
      retryAfterSeconds(new APIError(429, 'rate_limited', 'x', { retry_after_seconds: 7 })),
    ).toBe(7);
    expect(retryAfterSeconds(new APIError(429, 'rate_limited', 'x'))).toBeNull();
    expect(retryAfterSeconds(new TypeError('x'))).toBeNull();
  });
});
