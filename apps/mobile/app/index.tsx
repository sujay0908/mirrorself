/**
 * Root route - the _layout's auth gate redirects to the correct stack.
 *
 * This screen renders briefly during that redirect, so it is also the one
 * place a user sees if the gate cannot finish. When the post-sign-in twin
 * fetch fails terminally it says why and offers a retry, instead of showing
 * a spinner that will never resolve.
 */

import { ActivityIndicator, Button, StyleSheet, Text, View } from 'react-native';

import { apiFailureMessage } from '@/api/diagnostics';
import { config } from '@/config';
import { useSession } from '@/state/session';

export default function Index() {
  const twinStatus = useSession((s) => s.twinStatus);
  const twinFailure = useSession((s) => s.twinFailure);
  const setTwinStatus = useSession((s) => s.setTwinStatus);

  if (twinStatus === 'failed') {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Could not load your Twin</Text>
        <Text style={styles.body}>
          {apiFailureMessage(twinFailure, config.apiUrl)}
        </Text>
        {/* Back to 'idle' is all a retry needs: the gate re-runs the fetch. */}
        <Button title="Try again" onPress={() => setTwinStatus('idle')} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  title: { fontSize: 18, fontWeight: '700', textAlign: 'center' },
  body: { fontSize: 14, color: '#4b5563', textAlign: 'center' },
});
