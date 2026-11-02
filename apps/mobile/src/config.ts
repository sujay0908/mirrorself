/**
 * Build-time configuration for the mobile app.
 *
 * Every value comes from an `EXPO_PUBLIC_*` env variable so it is bundled at
 * build time. NEVER put secrets here — anything read from `process.env` on
 * device ships to the user.
 */

const readEnv = (key: string): string => {
  const value = process.env[key];
  if (!value) {
    throw new Error(
      `Missing required env var: ${key}. Expo loads apps/mobile/.env at ` +
        `dev-server start, so set it there (see .env.example at the repo ` +
        `root for the full list) and restart \`expo start\`.`,
    );
  }
  return value;
};

/** Positive integer env var, or the fallback when unset/invalid. */
const readIntEnv = (key: string, fallback: number): number => {
  const raw = process.env[key];
  const parsed = raw === undefined ? Number.NaN : Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

/**
 * Public URL env var. Required in a production bundle: a release that silently
 * falls back to localhost looks healthy at build time and then fails for every
 * real user, which is indistinguishable from the backend being down.
 */
const readPublicUrl = (key: string, devFallback: string): string => {
  const value = process.env[key];
  if (value) return value;
  if (process.env.NODE_ENV === 'production') {
    throw new Error(
      `Missing required env var: ${key}. A production web build must be given ` +
        `the public API origin; it must never fall back to localhost.`,
    );
  }
  return devFallback;
};

export const config = {
  apiUrl: readPublicUrl('EXPO_PUBLIC_API_URL', 'http://localhost:8000'),
  // Without a deadline a hung backend leaves every caller awaiting forever,
  // which the UI can only render as an endless spinner.
  apiTimeoutMs: readIntEnv('EXPO_PUBLIC_API_TIMEOUT_MS', 15_000),
  supabaseUrl: readEnv('EXPO_PUBLIC_SUPABASE_URL'),
  supabaseAnonKey: readEnv('EXPO_PUBLIC_SUPABASE_ANON_KEY'),
} as const;

export type AppConfig = typeof config;
