/**
 * The auth gate's decision, as a pure function.
 *
 * Kept out of the layout component (and free of react-native / expo-router
 * imports) so the routing rules can be unit-tested directly.
 */

export type AuthRoute =
  | '/'
  | '/(auth)/login'
  | '/(main)/home'
  | '/(onboarding)/create-twin';

/**
 * Progress of the one GET /v1/twin the gate performs after sign-in.
 *
 * Success is NOT a status - it is represented by the twin itself being in
 * the store. Every other outcome must be terminal: before this existed, a
 * failed fetch left the gate asking for the same fetch forever and the app
 * rendered its loading spinner with nothing behind it.
 */
export type TwinLoadStatus =
  /** Not attempted, or ready to attempt again. */
  | 'idle'
  /** In flight - do not start a second request. */
  | 'loading'
  /** The API answered 404: this user has no twin yet. */
  | 'absent'
  /** Unreachable, timed out, rejected, or errored. Terminal. */
  | 'failed';

export type AuthGateAction =
  /** Session state is still loading - never redirect yet. */
  | { kind: 'wait' }
  /** The current route is the right one. */
  | { kind: 'stay' }
  /** Signed in but the twin is not loaded yet; fetch it. */
  | { kind: 'loadTwin' }
  /** The twin load failed for good; show the user why. */
  | { kind: 'showError' }
  | { kind: 'redirect'; href: AuthRoute };

export interface AuthGateInput {
  /** False until the initial Supabase session read has settled. */
  isReady: boolean;
  hasUser: boolean;
  hasTwin: boolean;
  twinStatus: TwinLoadStatus;
  /** First expo-router segment: '(auth)' | '(main)' | '(onboarding)' | undefined. */
  segment: string | undefined;
}

export function authGateAction({
  isReady,
  hasUser,
  hasTwin,
  twinStatus,
  segment,
}: AuthGateInput): AuthGateAction {
  // Supabase parses the magic-link callback URL during its own init, and
  // getSession() awaits that. Redirecting before isReady would race it and
  // bounce a valid callback back to the login screen.
  if (!isReady) return { kind: 'wait' };

  if (!hasUser) {
    return segment === '(auth)'
      ? { kind: 'stay' }
      : { kind: 'redirect', href: '/(auth)/login' };
  }

  if (hasTwin) {
    // Signed in with a twin: anything outside the main stack (login screen,
    // onboarding, the bare root route) is a leftover and should go home.
    return segment === '(main)'
      ? { kind: 'stay' }
      : { kind: 'redirect', href: '/(main)/home' };
  }

  // Signed in, no twin in memory. The onboarding stack is where a user
  // without one belongs, so leave them to fill the form in peace.
  if (segment === '(onboarding)') return { kind: 'stay' };

  switch (twinStatus) {
    case 'loading':
      // A request is already in flight; a second one would race it.
      return { kind: 'wait' };
    case 'absent':
      return { kind: 'redirect', href: '/(onboarding)/create-twin' };
    case 'failed':
      // Terminal. The root route is the screen that renders the reason, so
      // anywhere else goes there rather than sitting on a dead spinner.
      return segment === undefined
        ? { kind: 'showError' }
        : { kind: 'redirect', href: '/' };
    default:
      return { kind: 'loadTwin' };
  }
}
