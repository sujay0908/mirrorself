/**
 * Magic-link sign-in regression tests.
 *
 * Supabase's implicit flow hands the session back in the callback URL (the
 * hash fragment). supabase-js only reads it when `detectSessionInUrl` is
 * enabled, and it was disabled on every platform — so on web the link was
 * ignored, no session was created, and the auth gate sent the user straight
 * back to /login. These tests pin the per-platform auth options and the
 * login screen's redirect target.
 *
 * No real tokens, sessions or secrets are used anywhere here.
 */

import { magicLinkRedirectTo } from '@/auth/redirect';
import { authGateAction } from '@/auth/route-guard';

const mockCreateClient = jest.fn(() => ({ auth: {} }));

jest.mock('react-native-url-polyfill/auto', () => ({}));
jest.mock('@supabase/supabase-js', () => ({
  createClient: mockCreateClient,
}));
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));
jest.mock('@/config', () => ({
  config: {
    apiUrl: 'http://localhost:8000',
    supabaseUrl: 'https://example.supabase.co',
    supabaseAnonKey: 'test-anon-key',
  },
}));

interface TestStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

interface TestAuthOptions {
  detectSessionInUrl: boolean;
  persistSession: boolean;
  autoRefreshToken: boolean;
  storage: TestStorage;
}

/** Re-import the client module with a given Platform.OS and capture options. */
function authOptionsFor(platformOS: string): TestAuthOptions {
  jest.resetModules();
  mockCreateClient.mockClear();
  jest.doMock('react-native', () => ({ Platform: { OS: platformOS } }));
  require('@/auth/supabase');
  const calls = mockCreateClient.mock.calls as unknown as Array<
    [string, string, { auth: TestAuthOptions }]
  >;
  expect(calls).toHaveLength(1);
  return calls[0][2].auth;
}

describe('magicLinkRedirectTo (login redirect behaviour)', () => {
  it('sends the web magic link back to the current origin', () => {
    expect(magicLinkRedirectTo('web', 'http://localhost:8081')).toBe(
      'http://localhost:8081',
    );
  });

  it('stays undefined on native so the app scheme / Site URL still applies', () => {
    expect(magicLinkRedirectTo('ios', 'http://localhost:8081')).toBeUndefined();
    expect(magicLinkRedirectTo('android')).toBeUndefined();
  });

  it('omits the redirect when there is no origin to return to', () => {
    expect(magicLinkRedirectTo('web', null)).toBeUndefined();
  });
});

describe('supabase client auth options (callback/session handling)', () => {
  it('reads the session out of the callback URL on web', () => {
    expect(authOptionsFor('web').detectSessionInUrl).toBe(true);
  });

  it('does not try to parse a callback URL on native', () => {
    expect(authOptionsFor('ios').detectSessionInUrl).toBe(false);
    expect(authOptionsFor('android').detectSessionInUrl).toBe(false);
  });

  it('persists and refreshes the session so a reload stays signed in', () => {
    const options = authOptionsFor('web');
    expect(options.persistSession).toBe(true);
    expect(options.autoRefreshToken).toBe(true);
  });

  it('round-trips the session through localStorage on web', async () => {
    const store: Record<string, string> = {};
    const g = globalThis as unknown as { localStorage?: unknown };
    g.localStorage = {
      getItem: (k: string): string | null => (k in store ? store[k] : null),
      setItem: (k: string, v: string): void => {
        store[k] = v;
      },
      removeItem: (k: string): void => {
        delete store[k];
      },
    };
    try {
      const { storage } = authOptionsFor('web');
      await storage.setItem('sb-session-test', 'opaque-value');
      expect(await storage.getItem('sb-session-test')).toBe('opaque-value');
      await storage.removeItem('sb-session-test');
      expect(await storage.getItem('sb-session-test')).toBeNull();
    } finally {
      delete g.localStorage;
    }
  });
});

describe('authGateAction (route guard after the magic-link callback)', () => {
  const base = {
    isReady: true,
    hasUser: false,
    hasTwin: false,
    twinStatus: 'idle' as const,
    segment: undefined as string | undefined,
  };

  it('never redirects before the session read has settled', () => {
    expect(
      authGateAction({ ...base, isReady: false, segment: '(main)' }),
    ).toEqual({ kind: 'wait' });
  });

  it('sends a signed-out visitor to the login screen', () => {
    expect(authGateAction({ ...base, segment: '(main)' })).toEqual({
      kind: 'redirect',
      href: '/(auth)/login',
    });
  });

  it('leaves a signed-out visitor on the login screen', () => {
    expect(authGateAction({ ...base, segment: '(auth)' })).toEqual({
      kind: 'stay',
    });
  });

  it('loads the twin for a user who just signed in on the login screen', () => {
    // Regression: the gate used to skip the (auth) group here, so a user who
    // completed the magic link while /login was mounted sat on the form.
    expect(
      authGateAction({ ...base, hasUser: true, segment: '(auth)' }),
    ).toEqual({ kind: 'loadTwin' });
  });

  it('loads the twin on the root route the magic link lands on', () => {
    expect(authGateAction({ ...base, hasUser: true })).toEqual({
      kind: 'loadTwin',
    });
  });

  it('leaves a twinless user alone inside onboarding', () => {
    expect(
      authGateAction({ ...base, hasUser: true, segment: '(onboarding)' }),
    ).toEqual({ kind: 'stay' });
  });

  it('sends a fully signed-in user home from the callback route', () => {
    // Regression: the root route was not covered, so a successful callback
    // left the user on the bare loading spinner.
    expect(
      authGateAction({ ...base, hasUser: true, hasTwin: true }),
    ).toEqual({ kind: 'redirect', href: '/(main)/home' });
  });

  it('sends a fully signed-in user home from login and onboarding', () => {
    for (const segment of ['(auth)', '(onboarding)']) {
      expect(
        authGateAction({ ...base, hasUser: true, hasTwin: true, segment }),
      ).toEqual({ kind: 'redirect', href: '/(main)/home' });
    }
  });

  it('does not bounce a signed-in user who is already in the app', () => {
    expect(
      authGateAction({
        ...base,
        hasUser: true,
        hasTwin: true,
        segment: '(main)',
      }),
    ).toEqual({ kind: 'stay' });
  });
});
