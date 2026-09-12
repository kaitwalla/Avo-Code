import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { api } from '@/lib/api';
import { loadConnection, saveConnection } from '@/lib/storage';
import { Card, PrimaryButton, Screen, SectionTitle } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

export default function SettingsScreen() {
  const [apiUrl, setApiUrl] = useState('');
  const [token, setToken] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    void loadConnection().then((value) => {
      setApiUrl(value.apiUrl);
      setToken(value.token);
    });
  }, []);

  const save = async () => {
    await saveConnection(apiUrl.trim(), token.trim());
    try {
      const health = await api.health();
      setStatus(`Connected · auth ${health.auth ? 'enabled' : 'disabled'}`);
    } catch (err) {
      setStatus(err instanceof Error ? `Saved, but connection failed: ${err.message}` : 'Saved, but connection failed');
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.shell}>
        <View style={styles.header}>
          <Text style={styles.title}>Connection</Text>
          <Text style={styles.subtitle}>One Avo backend serves both the responsive web app and the native iOS app.</Text>
        </View>
        <Card style={styles.form}>
          <SectionTitle>Backend</SectionTitle>
          <Text style={styles.label}>API URL</Text>
          <TextInput autoCapitalize="none" autoCorrect={false} value={apiUrl} onChangeText={setApiUrl} style={styles.input} placeholder="https://avo.example.com" placeholderTextColor={palette.muted} />
          <Text style={styles.label}>API token</Text>
          <TextInput autoCapitalize="none" autoCorrect={false} secureTextEntry value={token} onChangeText={setToken} style={styles.input} placeholder="Optional when AVO_WEB_TOKEN is unset" placeholderTextColor={palette.muted} />
          <PrimaryButton label="Save and test" onPress={save} />
          {status ? <Text style={styles.status}>{status}</Text> : null}
        </Card>
        <Card style={styles.note}>
          <Text style={styles.noteTitle}>Credential storage</Text>
          <Text style={styles.noteText}>On iOS the API token lives in Keychain through Expo SecureStore. On web it is browser-local, so remote deployments should use HTTPS and a scoped token.</Text>
        </Card>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  shell: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: spacing.md, paddingBottom: 90, gap: spacing.lg },
  header: { gap: 6, marginTop: spacing.sm },
  title: { color: palette.text, fontSize: 30, fontWeight: '800' },
  subtitle: { color: palette.muted, lineHeight: 21 },
  form: { gap: spacing.sm },
  label: { color: palette.muted, fontSize: 12, fontWeight: '700' },
  input: { minHeight: 48, backgroundColor: palette.panelRaised, borderColor: palette.border, borderWidth: 1, borderRadius: 12, color: palette.text, paddingHorizontal: 14, fontSize: 16 },
  status: { color: palette.accent, fontSize: 13 },
  note: { gap: 6 },
  noteTitle: { color: palette.text, fontSize: 15, fontWeight: '700' },
  noteText: { color: palette.muted, lineHeight: 20, fontSize: 13 },
});
