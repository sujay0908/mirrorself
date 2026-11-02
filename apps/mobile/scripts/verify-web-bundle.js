#!/usr/bin/env node
/**
 * Assert the exported web bundle actually contains its configuration.
 *
 * `expo export` succeeds whether or not EXPO_PUBLIC_* values were substituted,
 * because substitution is a Babel source transform rather than a build step
 * that can fail. A computed `process.env[key]` read is invisible to that
 * transform, so the export can be green while every value is `undefined` and
 * the deployed page throws on load and renders blank.
 *
 * check-web-env.js proves the values were PRESENT at build time; this proves
 * they LANDED in the artifact. Values are compared, never printed.
 */
const fs = require('fs');
const path = require('path');

const distDir = path.resolve(__dirname, '..', 'dist');
const bundleDir = path.join(distDir, '_expo', 'static', 'js', 'web');

if (!fs.existsSync(bundleDir)) {
  console.error(`Cannot verify the web bundle: ${bundleDir} does not exist.`);
  process.exit(1);
}

const bundles = fs
  .readdirSync(bundleDir)
  .filter((name) => name.endsWith('.js'))
  .map((name) => fs.readFileSync(path.join(bundleDir, name), 'utf8'));

if (bundles.length === 0) {
  console.error(`Cannot verify the web bundle: no .js emitted in ${bundleDir}.`);
  process.exit(1);
}

const contains = (needle) => bundles.some((source) => source.includes(needle));

const failures = [];

// Each configured value must appear in the artifact.
for (const key of [
  'EXPO_PUBLIC_API_URL',
  'EXPO_PUBLIC_SUPABASE_URL',
  'EXPO_PUBLIC_SUPABASE_ANON_KEY',
]) {
  const value = process.env[key];
  if (!value) {
    failures.push(`${key} was not set in the build environment.`);
  } else if (!contains(value)) {
    failures.push(
      `${key} was set but its value is absent from the bundle. Expo inlines ` +
        `only static \`process.env.NAME\` reads; a computed \`process.env[key]\` ` +
        `is never substituted. Check src/config.ts.`,
    );
  }
}

// The dev fallback must never survive into a deployed artifact.
if (contains('http://localhost:8000')) {
  failures.push(
    'The localhost dev fallback is present in the bundle; the deployed app ' +
      'would call localhost instead of the public API.',
  );
}

if (failures.length > 0) {
  console.error('Web bundle verification failed:');
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(
  'Web bundle verified: API origin, Supabase URL and publishable key are ' +
    'inlined, and no localhost fallback is present.',
);
