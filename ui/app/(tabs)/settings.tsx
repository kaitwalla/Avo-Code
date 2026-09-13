import { useCallback, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { api, AuthStatus, PasskeyCredential } from '@/lib/api';
import { addPasskey, signOut } from '@/lib/auth';
import { apiBaseUrl } from '@/lib/storage';
import { Card, PrimaryButton, Screen, SectionTitle } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

export default function SettingsScreen() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [credentials, setCredentials] = useState<PasskeyCredential[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextStatus, nextCredentials] = await Promise.all([api.authStatus(), api.credentials()]);
      setStatus(nextStatus);
      setCredentials(nextCredentials);
      setMessage('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const add = async () => {
    setBusy(true);
    setMessage('');
    try {
      await addPasskey();
      await load();
      setMessage('Passkey added.');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      await signOut();
      router.replace('/login');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.shell}>
        <View style={styles.header}>
          <Text style={styles.title}>Security</Text>
          <Text style={styles.subtitle}>Avo is single-user. Passkeys are the account.</Text>
        </View>

        <Card style={styles.card}>
          <SectionTitle>Passkeys</SectionTitle>
          <Text style={styles.summary}>{status?.passkey_count ?? credentials.length} registered</Text>
          <View style={styles.credentials}>
            {credentials.map((credential) => (
              <View key={credential.id} style={styles.credential}>
                <View style={styles.credentialText}>
                  <Text style={styles.credentialTitle}>{credential.label}</Text>
                  <Text style={styles.meta}>
                    {credential.backed_up ? 'Synced passkey' : credential.device_type || 'Passkey'}
                  </Text>
                </View>
                <Text style={styles.meta}>{credential.last_used_at ? 'Used' : 'New'}</Text>
              </View>
            ))}
          </View>
          <PrimaryButton label={busy ? 'Waiting…' : 'Add passkey'} onPress={add} disabled={busy} />
          {message ? <Text style={styles.message}>{message}</Text> : null}
        </Card>

        <Card style={styles.card}>
          <SectionTitle>Service</SectionTitle>
          <View style={styles.row}>
            <Text style={styles.label}>Backend</Text>
            <Text style={styles.value}>{apiBaseUrl() || 'Same origin'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>Relying party</Text>
            <Text style={styles.value}>{status?.rp_id ?? '…'}</Text>
          </View>
          <Text style={styles.note}>The web app and API share one origin. Native iOS uses the same backend and stores only its opaque session token in Keychain.</Text>
        </Card>

        <Card style={styles.card}>
          <SectionTitle>Session</SectionTitle>
          <PrimaryButton label={busy ? 'Working…' : 'Sign out'} onPress={logout} disabled={busy} />
        </Card>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  shell: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: spacing.md, paddingBottom: 110, gap: spacing.lg },
  header: { gap: 6, marginTop: spacing.sm },
  title: { color: palette.text, fontSize: 30, fontWeight: '800' },
  subtitle: { color: palette.muted, lineHeight: 21 },
  card: { gap: spacing.md },
  summary: { color: palette.accent, fontSize: 14, fontWeight: '700' },
  credentials: { gap: spacing.sm },
  credential: { minHeight: 58, backgroundColor: palette.panelRaised, borderRadius: 12, padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  credentialText: { flex: 1, gap: 3 },
  credentialTitle: { color: palette.text, fontSize: 15, fontWeight: '700' },
  meta: { color: palette.muted, fontSize: 12 },
  message: { color: palette.accent, fontSize: 13 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  label: { color: palette.muted, fontSize: 13 },
  value: { color: palette.text, fontSize: 13, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  note: { color: palette.muted, fontSize: 13, lineHeight: 20 },
});
