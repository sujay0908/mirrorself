import { Stack } from 'expo-router';

import { LoadingScreen } from '@/components/LoadingScreen';
import { useSession } from '@/state/session';
import { headerOptions } from '@/ui/theme';

/**
 * Every screen in here works on the signed-in person's Twin.
 *
 * After a page refresh or an opened link, the screen used to render before
 * the Twin had loaded, with empty or default values. The Profile form then
 * saved those defaults over the real profile. Nothing below renders until the
 * Twin is in the session; the root layout's auth gate is what loads it (and
 * sends the person to onboarding or an error screen if it cannot).
 */
export default function MainLayout() {
  const twin = useSession((s) => s.twin);
  if (!twin) return <LoadingScreen />;

  return (
    <Stack screenOptions={{ headerShown: true, ...headerOptions }}>
      {/* Home draws its own top bar. */}
      <Stack.Screen name="home" options={{ headerShown: false, title: 'MirrorSelf' }} />
      <Stack.Screen name="chat/[id]" options={{ title: twin.display_name }} />
      <Stack.Screen name="goals/index" options={{ title: 'Goals' }} />
      <Stack.Screen name="goals/new" options={{ title: 'New goal' }} />
      <Stack.Screen name="goals/[id]" options={{ title: 'Goal' }} />
      <Stack.Screen name="memories/index" options={{ title: 'Memories' }} />
      <Stack.Screen name="memories/[id]" options={{ title: 'Memory' }} />
      <Stack.Screen name="candidates/index" options={{ title: 'Review' }} />
      <Stack.Screen name="reflections/index" options={{ title: 'Reflections' }} />
      <Stack.Screen name="evolution/index" options={{ title: 'Evolution' }} />
      <Stack.Screen name="portrait/index" options={{ title: 'Self-portrait' }} />
      <Stack.Screen name="profile/index" options={{ title: 'Edit profile' }} />
    </Stack>
  );
}
