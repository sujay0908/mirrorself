/**
 * Minimal magic-link sign-in.
 *
 * Sprint 1 uses Supabase's OTP via email; a "we sent you a link" screen is
 * intentional — social sign-in is a Sprint 4+ item.
 */

import { useState } from 'react';
import {
  ActivityIndicator,
  Button,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { Alert } from '@/ui/alert';

import { magicLinkRedirectTo } from '@/auth/redirect';
import { supabase } from '@/auth/supabase';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit() {
    const address = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      Alert.alert('Please enter a valid email address.');
      return;
    }
    setLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email: address,
      options: {
        shouldCreateUser: true,
        // Without this Supabase falls back to the project's Site URL, which in
        // local development is usually not this dev server, so the link lands
        // somewhere that cannot complete the sign-in.
        emailRedirectTo: magicLinkRedirectTo(
          Platform.OS,
          typeof window !== 'undefined' ? window.location.origin : null,
        ),
      },
    });
    setLoading(false);
    if (error) {
      Alert.alert('Sign-in error', error.message);
      return;
    }
    setSent(true);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Personal AI Twin</Text>
      <Text style={styles.subtitle}>
        The avatar is the interface; the intelligence is the product.
      </Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        autoComplete="email"
        accessibilityLabel="Email address"
        onSubmitEditing={onSubmit}
        placeholder="you@example.com"
        value={email}
        onChangeText={setEmail}
        editable={!loading && !sent}
      />
      {loading ? (
        <ActivityIndicator />
      ) : sent ? (
        <View style={styles.sent}>
          <Text style={styles.info}>
            Check your email — we sent you a sign-in link. Open it on this
            device and browser.
          </Text>
          <Pressable onPress={() => setSent(false)} accessibilityRole="button">
            <Text style={styles.link}>Use a different email or send again</Text>
          </Pressable>
        </View>
      ) : (
        <Button title="Send sign-in link" onPress={onSubmit} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    justifyContent: 'center',
    gap: 16,
  },
  title: { fontSize: 28, fontWeight: '700' },
  subtitle: { fontSize: 15, color: '#4b5563' },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    padding: 12,
    borderRadius: 8,
  },
  info: { color: '#059669' },
  sent: { gap: 12 },
  link: { color: '#4f46e5', fontWeight: '600' },
});
