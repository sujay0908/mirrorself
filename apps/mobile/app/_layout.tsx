/**
 * Root layout. Bootstraps Supabase auth state and routes accordingly.
 */

import { useEffect } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { api, APIError } from '@/api/client';
import { logApiFailure } from '@/api/diagnostics';
import { authGateAction } from '@/auth/route-guard';
import { supabase } from '@/auth/supabase';
import { useSession } from '@/state/session';

function useAuthGate() {
  const router = useRouter();
  const segments = useSegments();
  const {
    userId,
    twin,
    isReady,
    twinStatus,
    setSession,
    setTwin,
    setTwinStatus,
    setReady,
  } = useSession();

  useEffect(() => {
    // Read the initial session, then subscribe for changes.
    supabase.auth
      .getSession()
      .then(({ data }) => {
        const user = data.session?.user ?? null;
        setSession({ userId: user?.id ?? null, email: user?.email ?? null });
        setReady(true);
      })
      .catch(() => {
        // A failed session read must not strand the app on the splash
        // spinner; fall through as unauthenticated.
        setSession({ userId: null, email: null });
        setReady(true);
      });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      const user = session?.user ?? null;
      setSession({ userId: user?.id ?? null, email: user?.email ?? null });
      if (!user) {
        setTwin(null);
        // Clear the terminal load state too, so the next sign-in refetches.
        setTwinStatus('idle');
      }
    });
    return () => sub.subscription.unsubscribe();
  }, [setSession, setReady, setTwin, setTwinStatus]);

  useEffect(() => {
    const action = authGateAction({
      isReady,
      hasUser: Boolean(userId),
      hasTwin: Boolean(twin),
      twinStatus,
      segment: segments[0],
    });

    if (action.kind === 'redirect') {
      router.replace(action.href);
      return;
    }
    if (action.kind !== 'loadTwin') return;

    // Mark in flight first: the gate returns 'wait' while loading, which is
    // what stops this effect from firing a second request on re-render.
    setTwinStatus('loading');
    api
      .getTwin()
      .then((loaded) => {
        setTwin(loaded);
        setTwinStatus('idle');
      })
      .catch((err: unknown) => {
        if (err instanceof APIError && err.status === 404) {
          // Expected for a new user - the gate routes them to onboarding.
          setTwinStatus('absent');
          return;
        }
        // Everything else (backend down, timeout, 401, 5xx) used to be
        // swallowed here, leaving the app on a spinner forever. Record it as
        // a terminal state the UI can explain.
        setTwinStatus('failed', logApiFailure('GET /v1/twin', err));
      });
  }, [
    isReady,
    userId,
    twin,
    twinStatus,
    segments,
    router,
    setTwin,
    setTwinStatus,
  ]);
}

export default function RootLayout() {
  useAuthGate();
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false }} />
    </SafeAreaProvider>
  );
}
