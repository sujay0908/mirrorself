/**
 * Magic-link sign-in.
 *
 * Supabase OTP via email: the person types an address, gets a link, opens it
 * on this device. The screen also says, briefly, what MirrorSelf is and the
 * promise it makes (you approve what it remembers) — this is the first thing
 * anyone sees.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { magicLinkRedirectTo } from '@/auth/redirect';
import { supabase } from '@/auth/supabase';
import { Button, Card, TextField } from '@/ui/kit';
import { colors, radius, space, type } from '@/ui/theme';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const PROMISES = [
  { emoji: '💬', text: 'Learns from your conversations' },
  { emoji: '✅', text: 'Only remembers what you approve' },
  { emoji: '✏️', text: 'Edit or delete anything, anytime' },
];

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    const address = email.trim();
    if (!EMAIL_RE.test(address)) {
      setError('Please enter a valid email address.');
      return;
    }
    setError(null);
    setLoading(true);
    const { error: authError } = await supabase.auth.signInWithOtp({
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
    if (authError) {
      setError(`We couldn't send the link: ${authError.message}`);
      return;
    }
    setSentTo(address);
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.column}>
          <View style={styles.brand}>
            <View style={styles.mark}>
              <Text style={styles.markEmoji}>🪞</Text>
            </View>
            <Text style={styles.wordmark}>MirrorSelf</Text>
            <Text style={styles.tagline}>
              An AI companion that gets to know you — and only remembers what you
              say it can.
            </Text>
          </View>

          <Card style={styles.card}>
            {sentTo ? (
              <View style={styles.sent}>
                <Text style={styles.sentEmoji}>✉️</Text>
                <Text style={type.title}>Check your inbox</Text>
                <Text style={styles.sentBody}>
                  We sent a sign-in link to{' '}
                  <Text style={styles.sentEmail}>{sentTo}</Text>. Open it on this
                  device and browser to continue.
                </Text>
                <Button
                  title="Use a different email"
                  variant="ghost"
                  onPress={() => setSentTo(null)}
                />
              </View>
            ) : (
              <>
                <Text style={type.title}>Sign in or create an account</Text>
                <Text style={styles.cardHint}>
                  No password needed. We&apos;ll email you a link.
                </Text>
                <TextField
                  label="Email"
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="email-address"
                  autoComplete="email"
                  accessibilityLabel="Email address"
                  onSubmitEditing={onSubmit}
                  placeholder="you@example.com"
                  value={email}
                  onChangeText={(t) => {
                    setEmail(t);
                    if (error) setError(null);
                  }}
                  editable={!loading}
                  error={error}
                />
                <Button
                  title="Send me a sign-in link"
                  size="lg"
                  onPress={onSubmit}
                  loading={loading}
                  style={styles.submit}
                />
              </>
            )}
          </Card>

          <View style={styles.promises}>
            {PROMISES.map((p) => (
              <View key={p.text} style={styles.promise}>
                <Text style={styles.promiseEmoji}>{p.emoji}</Text>
                <Text style={styles.promiseText}>{p.text}</Text>
              </View>
            ))}
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: space.xl },
  column: { width: '100%', maxWidth: 440, alignSelf: 'center', gap: space.xxl },
  brand: { alignItems: 'center', gap: space.sm },
  mark: {
    width: 72,
    height: 72,
    borderRadius: 24,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
  markEmoji: { fontSize: 36 },
  wordmark: { ...type.display, fontSize: 32 },
  tagline: { ...type.body, color: colors.muted, textAlign: 'center', maxWidth: 360 },
  card: { padding: space.xl, gap: space.md },
  cardHint: { ...type.small, marginTop: -6 },
  submit: { marginTop: space.xs },
  sent: { alignItems: 'center', gap: space.sm, paddingVertical: space.sm },
  sentEmoji: { fontSize: 40 },
  sentBody: { ...type.body, textAlign: 'center', color: colors.muted },
  sentEmail: { fontWeight: '700', color: colors.ink },
  promises: { gap: space.sm, paddingHorizontal: space.sm },
  promise: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  promiseEmoji: {
    fontSize: 16,
    width: 32,
    height: 32,
    lineHeight: 32,
    textAlign: 'center',
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    overflow: 'hidden',
  },
  promiseText: { ...type.body, color: colors.text },
});
