import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { api, AccessChange, AccessManifest, AccessPreview, AccessStatus } from '@/lib/api';
import { approveAccessChange } from '@/lib/auth';
import { Card, Pill, PrimaryButton, Screen, SectionTitle } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

function CapabilityRow({ name, detail, trailing }: { name: string; detail: string; trailing?: string }) {
  return (
    <View style={styles.row}>
      <View style={styles.rowCopy}>
        <Text style={styles.rowTitle}>{name}</Text>
        <Text numberOfLines={2} style={styles.rowDetail}>{detail}</Text>
      </View>
      {trailing ? <Text style={styles.trailing}>{trailing}</Text> : null}
    </View>
  );
}

function Empty({ children }: { children: string }) {
  return <Text style={styles.empty}>{children}</Text>;
}

function ManifestSummary({ manifest, status }: { manifest: AccessManifest; status: AccessStatus }) {
  const repos = Object.entries(manifest.repositories);
  const secrets = Object.entries(manifest.secrets);
  const services = Object.entries(manifest.services);
  const tools = Object.entries(manifest.tools).filter(([, value]) => value.enabled);
  const hosts = manifest.network.allow;
  return (
    <View style={styles.sections}>
      <Card style={styles.card}>
        <SectionTitle>Repositories</SectionTitle>
        {repos.length ? repos.map(([name, item]) => (
          <CapabilityRow key={name} name={name} detail={item.path} trailing={item.access} />
        )) : <Empty>No repositories granted.</Empty>}
      </Card>

      <Card style={styles.card}>
        <SectionTitle>Secrets</SectionTitle>
        <Text style={styles.note}>Only references are shown. Secret values never enter the manifest or API response.</Text>
        {secrets.length ? secrets.map(([name, item]) => {
          const configured = status.secret_status[name]?.configured ?? false;
          return (
            <CapabilityRow
              key={name}
              name={name}
              detail={`${item.source}${item.expose_to.length ? ` · ${item.expose_to.join(', ')}` : ''}`}
              trailing={configured ? 'configured' : 'missing'}
            />
          );
        }) : <Empty>No secrets granted.</Empty>}
      </Card>

      <Card style={styles.card}>
        <SectionTitle>Services</SectionTitle>
        {services.length ? services.map(([name, item]) => (
          <CapabilityRow key={name} name={name} detail={item.url} trailing={item.access} />
        )) : <Empty>No services granted.</Empty>}
      </Card>

      <Card style={styles.card}>
        <SectionTitle>Tools</SectionTitle>
        {tools.length ? tools.map(([name, item]) => (
          <CapabilityRow
            key={name}
            name={name}
            detail={item.expose_to.length ? `Available to ${item.expose_to.join(', ')}` : 'No role restriction declared'}
            trailing="enabled"
          />
        )) : <Empty>No tools granted.</Empty>}
      </Card>

      <Card style={styles.card}>
        <SectionTitle>Network</SectionTitle>
        {hosts.length ? hosts.map((host) => <CapabilityRow key={host} name={host} detail="Allowed outbound host" />) : <Empty>No network hosts granted.</Empty>}
      </Card>
    </View>
  );
}

function ChangeList({ changes }: { changes: AccessChange[] }) {
  if (!changes.length) return <Text style={styles.empty}>No capability changes.</Text>;
  return (
    <View style={styles.changes}>
      {changes.map((change, index) => (
        <View key={`${change.category}:${change.name}:${index}`} style={styles.change}>
          <Pill label={change.increase ? 'approval' : change.change} tone={change.increase ? 'warn' : 'neutral'} />
          <View style={styles.changeCopy}>
            <Text style={styles.changeTitle}>{change.category} · {change.name}</Text>
            <Text style={styles.changeText}>
              {change.increase ? 'Increases Avo’s authority and requires a fresh passkey.' : `${change.change} capability`}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

export default function AccessScreen() {
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [yaml, setYaml] = useState('');
  const [preview, setPreview] = useState<AccessPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    try {
      const next = await api.access();
      setStatus(next);
      setYaml(next.yaml);
      setPreview(null);
      setMessage('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const dirty = useMemo(() => status ? yaml !== status.yaml : false, [status, yaml]);

  const inspect = async () => {
    setBusy(true);
    setMessage('');
    try {
      const next = await api.previewAccess(yaml);
      setPreview(next);
      setMessage(next.requires_approval ? 'This edit contains privilege increases.' : 'This edit can be applied without increasing authority.');
    } catch (err) {
      setPreview(null);
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMessage('');
    try {
      const result = await api.applyAccess(yaml);
      if (result.requires_passkey && result.approval_id) {
        setMessage('Confirm the capability increase with your passkey…');
        const next = await approveAccessChange(result.approval_id);
        setStatus(next);
        setYaml(next.yaml);
        setPreview(null);
        setMessage('Access manifest updated and capability increase approved.');
      } else {
        const next = result.status ?? await api.access();
        setStatus(next);
        setYaml(next.yaml);
        setPreview(null);
        setMessage('Access manifest updated.');
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return (
      <Screen style={styles.loading}>
        <ActivityIndicator color={palette.accent} />
        <Text style={styles.loadingText}>{message || 'Loading Avo access…'}</Text>
      </Screen>
    );
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.shell} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <Text style={styles.eyebrow}>CAPABILITY MANIFEST</Text>
          <Text style={styles.title}>What Avo can touch</Text>
          <Text style={styles.subtitle}>
            Effective access is shown below. The source of truth is {status.path}; privilege increases do not become effective until you approve them with a passkey.
          </Text>
        </View>

        {status.requires_approval ? (
          <Card style={styles.warningCard}>
            <View style={styles.warningHeader}>
              <Pill label="pending" tone="warn" />
              <Text style={styles.warningTitle}>The repo requests more authority than is currently granted.</Text>
            </View>
            <ChangeList changes={status.changes} />
            <Text style={styles.note}>Saving the manifest below will ask for Face ID / Touch ID before these increases become effective.</Text>
          </Card>
        ) : null}

        <ManifestSummary manifest={status.effective} status={status} />

        <Card style={styles.editorCard}>
          <SectionTitle>Edit {status.path}</SectionTitle>
          <Text style={styles.note}>
            Secret entries accept only env:NAME or file:/path references. Literal secret values are rejected by the backend.
          </Text>
          <TextInput
            value={yaml}
            onChangeText={(value) => { setYaml(value); setPreview(null); }}
            multiline
            autoCapitalize="none"
            autoCorrect={false}
            spellCheck={false}
            textAlignVertical="top"
            style={styles.editor}
          />
          {preview ? (
            <View style={styles.preview}>
              <Text style={styles.previewTitle}>Preview</Text>
              <ChangeList changes={preview.changes} />
            </View>
          ) : null}
          <View style={styles.actions}>
            <Pressable disabled={busy} onPress={inspect} style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}>
              <Text style={styles.secondaryText}>Preview changes</Text>
            </Pressable>
            <View style={styles.primaryAction}>
              <PrimaryButton label={busy ? 'Working…' : dirty || status.requires_approval ? 'Save manifest' : 'Saved'} onPress={save} disabled={busy || (!dirty && !status.requires_approval)} />
            </View>
          </View>
          {message ? <Text style={styles.message}>{message}</Text> : null}
        </Card>
      </ScrollView>
    </Screen>
  );
}

const mono = Platform.select({ ios: 'Menlo', default: 'monospace' });

const styles = StyleSheet.create({
  shell: { width: '100%', maxWidth: 920, alignSelf: 'center', padding: spacing.md, paddingBottom: 80, gap: spacing.lg },
  header: { gap: 6, marginTop: spacing.sm },
  eyebrow: { color: palette.accent, fontSize: 11, fontWeight: '900', letterSpacing: 1.4 },
  title: { color: palette.text, fontSize: 30, lineHeight: 36, fontWeight: '800' },
  subtitle: { color: palette.muted, fontSize: 14, lineHeight: 21 },
  sections: { gap: spacing.md },
  card: { gap: spacing.sm },
  row: { minHeight: 54, paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: palette.border, flexDirection: 'row', alignItems: 'center', gap: 12 },
  rowCopy: { flex: 1, gap: 3 },
  rowTitle: { color: palette.text, fontSize: 14, fontWeight: '700' },
  rowDetail: { color: palette.muted, fontSize: 12, lineHeight: 17 },
  trailing: { color: palette.accent, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  empty: { color: palette.muted, fontSize: 13, lineHeight: 19 },
  warningCard: { borderColor: palette.warn, gap: spacing.md },
  warningHeader: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  warningTitle: { color: palette.text, fontSize: 14, lineHeight: 20, fontWeight: '700', flex: 1 },
  changes: { gap: 10 },
  change: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  changeCopy: { flex: 1, gap: 2 },
  changeTitle: { color: palette.text, fontSize: 13, fontWeight: '700' },
  changeText: { color: palette.muted, fontSize: 12, lineHeight: 17 },
  note: { color: palette.muted, fontSize: 12, lineHeight: 18 },
  editorCard: { gap: spacing.md },
  editor: { minHeight: 330, maxHeight: 620, borderWidth: 1, borderColor: palette.border, borderRadius: 12, backgroundColor: palette.bg, color: palette.text, fontSize: 13, lineHeight: 19, padding: 12, fontFamily: mono },
  preview: { gap: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: palette.border, paddingTop: spacing.md },
  previewTitle: { color: palette.text, fontSize: 14, fontWeight: '800' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  secondary: { minHeight: 48, borderRadius: 14, borderWidth: 1, borderColor: palette.border, paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center' },
  secondaryText: { color: palette.text, fontSize: 14, fontWeight: '700' },
  primaryAction: { minWidth: 180, flexGrow: 1 },
  pressed: { opacity: 0.75 },
  message: { color: palette.accent, fontSize: 13, lineHeight: 19 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  loadingText: { color: palette.muted, fontSize: 14 },
});
