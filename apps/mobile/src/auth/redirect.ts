/**
 * Where Supabase should send the magic link back to.
 *
 * Kept free of react-native imports so it stays unit-testable in the plain
 * node test environment.
 */

export function magicLinkRedirectTo(
  platformOS: string,
  origin?: string | null,
): string | undefined {
  // Native opens the link via the app scheme / Supabase Site URL, unchanged.
  if (platformOS !== 'web') return undefined;
  return origin ?? undefined;
}
