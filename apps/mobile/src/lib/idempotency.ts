/**
 * Idempotency keys for chat sends.
 *
 * A send carries a key; sending the same key again returns the exchange the
 * server already stored instead of creating a second one. The key therefore
 * has to stay the same across retries of one draft and change as soon as the
 * person sends something different.
 *
 * Pure (no react-native imports) so it runs in the node test environment.
 */

const ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';

/** 26 characters from [a-z0-9-]; matches the API's accepted key format. */
export function newIdempotencyKey(random: () => number = Math.random): string {
  let suffix = '';
  for (let i = 0; i < 16; i += 1) {
    suffix += ALPHABET[Math.floor(random() * ALPHABET.length) % ALPHABET.length];
  }
  return `m-${Date.now().toString(36)}-${suffix}`;
}

export interface PendingSend {
  content: string;
  key: string;
}

/**
 * The key to use for sending `content`. Reuses the previous attempt's key when
 * the text is unchanged (a retry), otherwise mints a new one.
 */
export function keyForSend(
  previous: PendingSend | null,
  content: string,
  mint: () => string = newIdempotencyKey,
): PendingSend {
  if (previous && previous.content === content) return previous;
  return { content, key: mint() };
}
