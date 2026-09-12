import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { api, RunSummary } from '@/lib/api';
import { Card, Pill, PrimaryButton, Screen } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

function tone(status: string) {
  if (status === 'accepted') return 'good' as const;
  if (status === 'running') return 'warn' as const;
  if (status === 'failed') return 'bad' as const;
  return 'neutral' as const;
}

export default function RunsScreen() {
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [objective, setObjective] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      setRuns(await api.runs());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useEffect(() => {
    const timer = setInterval(() => void load(), 3500);
    return () => clearInterval(timer);
  }, [load]);

  const start = async () => {
    if (!objective.trim()) return;
    setLoading(true);
    try {
      await api.start(objective.trim());
      setObjective('');
      setTimeout(() => void load(), 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen>
      <View style={[styles.shell, wide && styles.shellWide]}>
        <View style={[styles.composeColumn, wide && styles.composeWide]}>
          <Text style={styles.eyebrow}>AVO CONTROL PLANE</Text>
          <Text style={styles.title}>What should the team work on?</Text>
          <Text style={styles.subtitle}>Start with the task. Avo decides how much agent machinery it deserves.</Text>
          <Card style={styles.composer}>
            <TextInput
              multiline
              value={objective}
              onChangeText={setObjective}
              placeholder="Fix the auth redirect loop without changing the session format…"
              placeholderTextColor={palette.muted}
              style={styles.input}
              textAlignVertical="top"
            />
            <PrimaryButton label={loading ? 'Starting…' : 'Start run'} onPress={start} disabled={loading || !objective.trim()} />
          </Card>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>

        <View style={[styles.runsColumn, wide && styles.runsWide]}>
          <View style={styles.headingRow}>
            <Text style={styles.heading}>Runs</Text>
            <Text style={styles.count}>{runs.length}</Text>
          </View>
          <FlatList
            data={runs}
            keyExtractor={(item) => item.id}
            refreshControl={<RefreshControl refreshing={false} onRefresh={load} tintColor={palette.accent} />}
            contentContainerStyle={styles.list}
            renderItem={({ item }) => (
              <Pressable onPress={() => router.push(`/runs/${item.id}`)} style={({ pressed }) => pressed && { opacity: 0.75 }}>
                <Card style={styles.runCard}>
                  <View style={styles.runTop}>
                    <Pill label={item.status} tone={tone(item.status)} />
                    <Text style={styles.score}>{item.best_score.toFixed(2)}</Text>
                  </View>
                  <Text numberOfLines={3} style={styles.objective}>{item.objective}</Text>
                  <Text numberOfLines={1} style={styles.repo}>{item.repo_path}</Text>
                </Card>
              </Pressable>
            )}
            ListEmptyComponent={<Text style={styles.empty}>No runs yet. Start one above.</Text>}
          />
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  shell: { flex: 1, padding: spacing.md, gap: spacing.lg, width: '100%', alignSelf: 'center' },
  shellWide: { maxWidth: 1220, flexDirection: 'row', padding: spacing.xl },
  composeColumn: { gap: spacing.sm },
  composeWide: { width: 390, paddingTop: 28 },
  runsColumn: { flex: 1, minHeight: 320 },
  runsWide: { paddingLeft: spacing.lg },
  eyebrow: { color: palette.accent, letterSpacing: 1.5, fontWeight: '800', fontSize: 12 },
  title: { color: palette.text, fontSize: 30, lineHeight: 35, fontWeight: '800' },
  subtitle: { color: palette.muted, fontSize: 15, lineHeight: 22, marginBottom: spacing.sm },
  composer: { gap: spacing.md },
  input: { minHeight: 126, color: palette.text, fontSize: 17, lineHeight: 24 },
  error: { color: palette.bad, fontSize: 13 },
  headingRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginBottom: spacing.sm },
  heading: { color: palette.text, fontSize: 24, fontWeight: '800' },
  count: { color: palette.muted, fontSize: 14 },
  list: { gap: spacing.sm, paddingBottom: 90 },
  runCard: { gap: 10 },
  runTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  score: { color: palette.text, fontSize: 20, fontWeight: '800', fontVariant: ['tabular-nums'] },
  objective: { color: palette.text, fontSize: 16, lineHeight: 22, fontWeight: '600' },
  repo: { color: palette.muted, fontSize: 12 },
  empty: { color: palette.muted, textAlign: 'center', paddingVertical: 40 },
});
