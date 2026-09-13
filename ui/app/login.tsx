import { useEffect, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { router } from 'expo-router';
import { api, AuthStatus } from '@/lib/api';
import { enrollFirstPasskey, signInWithPasskey } from '@/lib/auth';
import { Card, PrimaryButton, Screen } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

export default function LoginScreen() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const next = await api.authStatus();
      if (next.authenticated) {
        router.replace('/(tabs)' as never);
        return;
      }
      setStatus(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => { void load(); }, []);

  const authenticate = async () => {
    setBusy(true);
    setError('');
    try {
      if (status?.bootstrap_required) {
        if (!code.trim()) throw new Error('Enter the one-time enrollment code first');
        await enrollFirstPasskey(code);
      } else {
        await signInWithPasskey();
      }
      router.replace('/(tabs)' as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!status && !error) {
    return (
      <Screen style={styles.center}>
        <ActivityIndicator color={palette.accent} />
        <Text style={styles.loading}>Checking Avo…</Text>
      </Screen>
    );
  }

  const bootstrap = Boolean(status?.bootstrap_required);

  return (
    <Screen>
      <KeyboardAvoidingView style={styles.center} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.shell}>
          <Text style={styles.eyebrow}>AVO CONTROL PLANE</Text>
          <Text style={styles.title}>{bootstrap ? 'Create your passkey' : 'Unlock Avo'}</Text>
          <Text style={styles.subtitle}>
            {bootstrap
              ? 'Use the one-time code from the Avo host, then save a passkey with Face ID, Touch ID, or your password manager.'
              : 'Use your passkey to continue. No password or API token required.'}
          </Text>

          <Card style={styles.card}>
            {bootstrap ? (
              <>
                <Text style={styles.label}>Enrollment code</Text>
                <TextInput
                  autoCapitalize="characters"
                  autoCorrect={false}
                  value={code}
                  onChangeText={setCode}
                  placeholder="ABCD-EF01-2345-6789"
                  placeholderTextColor={palette.muted}
                  style={styles.input}
                  returnKeyType="done"
                />
              </>
            ) : null}
            <PrimaryButton
              label={busy ? 'Waiting for passkey…' : bootstrap ? 'Create passkey' : 'Sign in with passkey'}
              onPress={authenticate}
              disabled={busy || (bootstrap && !code.trim())}
            />
            {error ? <Text style={styles.error}>{error}</Text> : null}
          </Card>

          {bootstrap ? (
            <Text style={styles.help}>On the server: avo-harness auth bootstrap -c avo.json</Text>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, padding: spacing.lg },
  shell: { width: '100%', maxWidth: 480, gap: spacing.sm },
  eyebrow: { color: palette.accent, letterSpacing: 1.8, fontWeight: '800', fontSize: 12 },
  title: { color: palette.text, fontSize: 34, lineHeight: 40, fontWeight: '800' },
  subtitle: { color: palette.muted, fontSize: 16, lineHeight: 23, marginBottom: spacing.md },
  card: { gap: spacing.md },
  label: { color: palette.muted, fontSize: 12, fontWeight: '700' },
  input: { minHeight: 52, backgroundColor: palette.panelRaised, borderColor: palette.border, borderWidth: 1, borderRadius: 12, color: palette.text, paddingHorizontal: 14, fontSize: 18, letterSpacing: 1.2 },
  error: { color: palette.bad, lineHeight: 20 },
  help: { color: palette.muted, fontSize: 12, lineHeight: 18, textAlign: 'center', marginTop: spacing.sm },
  loading: { color: palette.muted },
});
