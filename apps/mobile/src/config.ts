/**
 * Build-time configuration for the mobile app.
 *
 * Every value comes from an `EXPO_PUBLIC_*` env variable so it is bundled at
 * build time. NEVER put secrets here — anything read from `process.env` on
 * device ships to the user.
 */

/**
 * Every public value is read through a STATIC `process.env.NAME` expression.
 *
 * This is not a style choice. `babel-preset-expo` substitutes `EXPO_PUBLIC_*`
 * values at build time by rewriting static member expressions in the source.
 * A computed read — `process.env[key]` — is invisible to that transform, so in
 * a static web export nothing is substituted, every value reads back
 * `undefined`, and the app throws on the first import and renders a blank
 * page. The dev server hides this, because there `process.env` exists at
 * runtime.
 *
 * Spelling each name out once here keeps the lookup static while the helpers
 * below stay generic. Adding a variable means adding it to this map.
 */
const PUBLIC_ENV = {
  EXPO_PUBLIC_API_URL: process.env.EXPO_PUBLIC_API_URL,
  EXPO_PUBLIC_API_TIMEOUT_MS: process.env.EXPO_PUBLIC_API_TIMEOUT_MS,
  EXPO_PUBLIC_SUPABASE_URL: process.env.EXPO_PUBLIC_SUPABASE_URL,
  EXPO_PUBLIC_SUPABASE_ANON_KEY: process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY,
} as const;

type PublicEnvKey = keyof typeof PUBLIC_ENV;

const readEnv = (key: PublicEnvKey): string => {
  const value = PUBLIC_ENV[key];
  if (!value) {
    throw new Error(
      `Missing required env var: ${key}. Expo loads apps/mobile/.env at ` +
        `dev-server start, so set it there (see .env.example at the repo ` +
        `root for the full list) and restart \`expo start\`. For a deployed ` +
        `build it must be set in the build environment.`,
    );
  }
  return value;
};

/** Positive integer env var, or the fallback when unset/invalid. */
const readIntEnv = (key: PublicEnvKey, fallback: number): number => {
  const raw = PUBLIC_ENV[key];
  const parsed = raw === undefined ? Number.NaN : Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

/**
 * Public URL env var. Required in a production bundle: a release that silently
 * falls back to localhost looks healthy at build time and then fails for every
 * real user, which is indistinguishable from the backend being down.
 */
const readPublicUrl = (key: PublicEnvKey, devFallback: string): string => {
  const value = PUBLIC_ENV[key];
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
