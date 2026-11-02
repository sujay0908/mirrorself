// metro.config.js -- pnpm monorepo configuration for Metro / Expo (web + native).
//
// Two pnpm-specific resolution problems are addressed:
//
// 1) ENTRY OUTSIDE THE PROJECT ROOT. The entry (expo-router/entry) lives in the
//    workspace-root pnpm store, outside apps/mobile. With the default
//    single-project config Metro serves it by an absolute path and the web
//    bundle 404s ("Unable to resolve ... entry"). Watching the workspace root
//    and resolving node_modules from both the app and the root puts the entry
//    inside Metro's served tree.
//
// 2) @babel/runtime NOT RESOLVABLE. babel-preset-expo compiles every app file to
//    code that requires @babel/runtime/helpers/*, but the app does not declare
//    @babel/runtime, so under pnpm's isolated node_modules it is not symlinked
//    at the app or workspace node_modules and Metro cannot resolve it. It is
//    present in the pnpm store; map it explicitly so Metro finds it without
//    flattening node_modules or reinstalling.
//
// This is the standard Expo monorepo setup and is correct for native too.
// See https://docs.expo.dev/guides/monorepos/
const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');
const fs = require('fs');

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, '../..');

const config = getDefaultConfig(projectRoot);

// (1) Watch the whole monorepo and resolve modules from both node_modules.
config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(workspaceRoot, 'node_modules'),
];

// (2) Map @babel/runtime to its real location in the pnpm store (it is not
//     symlinked at a standard node_modules path under pnpm's isolated linker).
function resolveInPnpmStore(dirPrefix, subPackage) {
  const store = path.join(workspaceRoot, 'node_modules', '.pnpm');
  try {
    const match = fs.readdirSync(store).find((name) => name.startsWith(dirPrefix));
    if (match) {
      const resolved = path.join(store, match, 'node_modules', subPackage);
      if (fs.existsSync(resolved)) return resolved;
    }
  } catch (err) {
    // no .pnpm store (hoisted install) -> leave default resolution
  }
  return null;
}

const babelRuntime = resolveInPnpmStore('@babel+runtime@', '@babel/runtime');
if (babelRuntime) {
  config.resolver.extraNodeModules = {
    ...(config.resolver.extraNodeModules || {}),
    '@babel/runtime': babelRuntime,
  };
}

module.exports = config;
