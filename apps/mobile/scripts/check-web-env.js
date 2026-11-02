#!/usr/bin/env node
/**
 * Fail the web build when a required EXPO_PUBLIC_* value is missing.
 *
 * `expo export` inlines these at build time, so an unset variable does not
 * fail the build -- it ships `undefined` into the bundle and the app breaks in
 * the browser for every visitor. Checking here turns that silent, late failure
 * into a loud build failure with the missing name.
 *
 * Values are never printed: only the names of the ones that are absent.
 */
const REQUIRED = [
  'EXPO_PUBLIC_API_URL',
  'EXPO_PUBLIC_SUPABASE_URL',
  'EXPO_PUBLIC_SUPABASE_ANON_KEY',
];

const missing = REQUIRED.filter((key) => !process.env[key]);

if (missing.length > 0) {
  console.error(
    'Cannot build the web bundle. Missing required environment ' +
      `variable(s): ${missing.join(', ')}.\n` +
      'Set them in the deployment environment (Vercel: Project Settings -> ' +
      'Environment Variables) or, for a local build, in apps/mobile/.env.',
  );
  process.exit(1);
}

const apiUrl = process.env.EXPO_PUBLIC_API_URL;
if (process.env.VERCEL === '1' && apiUrl.includes('localhost')) {
  console.error(
    'Cannot build the web bundle: EXPO_PUBLIC_API_URL points at localhost, ' +
      'which is unreachable from a deployed site. Set it to the public API ' +
      'origin.',
  );
  process.exit(1);
}
