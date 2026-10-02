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
      `Missing required env var: ${key}. See .env.example at the repo root.`,
    );
  }
  return value;
};

export const config = {
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000',
  supabaseUrl: readEnv('EXPO_PUBLIC_SUPABASE_URL'),
  supabaseAnonKey: readEnv('EXPO_PUBLIC_SUPABASE_ANON_KEY'),
} as const;

export type AppConfig = typeof config;
