/**
 * Root layout. Bootstraps Supabase auth state and routes accordingly.
 */

import { useEffect } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { api, APIError } from '@/api/client';
import { supabase } from '@/auth/supabase';
import { useSession } from '@/state/session';

function useAuthGate() {
  const router = useRouter();
  const segments = useSegments();
  const { userId, twin, isReady, setSession, setTwin, setReady } = useSession();

  useEffect(() => {
    // Read the initial session, then subscribe for changes.
    supabase.auth.getSession().then(({ data }) => {
      const user = data.session?.user ?? null;
      setSession({ userId: user?.id ?? null, email: user?.email ?? null });
      setReady(true);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      const user = session?.user ?? null;
      setSession({ userId: user?.id ?? null, email: user?.email ?? null });
      if (!user) setTwin(null);
    });
    return () => sub.subscription.unsubscribe();
  }, [setSession, setReady, setTwin]);

  useEffect(() => {
    if (!isReady) return;
    const inAuth = segments[0] === '(auth)';
    const inOnboarding = segments[0] === '(onboarding)';

    if (!userId && !inAuth) {
      router.replace('/(auth)/login');
      return;
    }
    if (userId && !twin && !inOnboarding && segments[0] !== '(auth)') {
      // Fetch or fall through to onboarding.
      api
        .getTwin()
        .then(setTwin)
        .catch((err: unknown) => {
          if (err instanceof APIError && err.status === 404) {
            router.replace('/(onboarding)/create-twin');
          }
        });
    }
    if (userId && twin && (inAuth || inOnboarding)) {
      router.replace('/(main)/home');
    }
  }, [isReady, userId, twin, segments, router, setTwin]);
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
