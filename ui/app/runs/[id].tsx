import { useCallback, useEffect, useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { api, RunDetail } from '@/lib/api';
import { Card, Pill, Screen, SectionTitle } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

function tone(status: string) {
  if (status === 'accepted') return 'good' as const;
  if (status === 'running') return 'warn' as const;
  if (status === 'failed') return 'bad' as const;
  return 'neutral' as const;
}

export default function RunDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setRun(await api.run(id));
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 2500);
    return () => clearInterval(timer);
  }, [load]);

  const totals = useMemo(() => {
    const input = run?.invocations.reduce((sum, x) => sum + (x.input_tokens ?? 0), 0) ?? 0;
    const output = run?.invocations.reduce((sum, x) => sum + (x.output_tokens ?? 0), 0) ?? 0;
    const cost = run?.invocations.reduce((sum, x) => sum + (x.cost_usd ?? 0), 0) ?? 0;
    return { input, output, cost };
  }, [run]);

  if (!run) {
    return <Screen><View style={styles.center}><Text style={error ? styles.error : styles.muted}>{error || 'Loading run…'}</Text></View></Screen>;
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={[styles.shell, wide && styles.shellWide]}>
        <View style={styles.hero}>
          <View style={styles.heroTop}>
            <Pill label={run.status} tone={tone(run.status)} />
            <Text style={styles.score}>{run.best_score.toFixed(2)}</Text>
          </View>
          <Text style={styles.title}>{run.objective}</Text>
          <Text style={styles.repo}>{run.repo_path}</Text>
        </View>

        <View style={[styles.columns, wide && styles.columnsWide]}>
          <View style={styles.column}>
            <SectionTitle>Progress</SectionTitle>
            <Card style={styles.stack}>
              {run.candidates.length ? run.candidates.map((item) => (
                <View key={item.iteration} style={styles.row}>
                  <Text style={styles.rowLabel}>Attempt {item.iteration}</Text>
                  <View style={styles.rowRight}>
                    {item.improved ? <Text style={styles.improved}>↑</Text> : null}
                    <Text style={styles.rowValue}>{item.score.toFixed(2)}</Text>
                  </View>
                </View>
              )) : <Text style={styles.muted}>Waiting for first candidate…</Text>}
            </Card>

            <SectionTitle>Evaluators</SectionTitle>
            <Card style={styles.stack}>
              {run.evaluations.map((item, index) => (
                <View key={`${item.iteration}-${item.name}-${index}`} style={styles.evalRow}>
                  <View style={styles.flex}>
                    <Text style={styles.rowLabel}>{item.name}</Text>
                    <Text numberOfLines={2} style={styles.small}>{item.summary}</Text>
                  </View>
                  <Pill label={item.passed ? 'pass' : 'fail'} tone={item.passed ? 'good' : 'bad'} />
                </View>
              ))}
            </Card>
          </View>

          <View style={styles.column}>
            <SectionTitle>Agent activity</SectionTitle>
            <Card style={styles.stack}>
              {run.role_runs.length ? [...run.role_runs].reverse().slice(0, 18).map((item, index) => (
                <View key={`${item.iteration}-${item.sequence}-${index}`} style={styles.agentBlock}>
                  <View style={styles.row}>
                    <Text style={styles.agent}>{item.role}</Text>
                    <Text style={styles.small}>{(item.duration_ms / 1000).toFixed(1)}s</Text>
                  </View>
                  <Text style={styles.reason}>{item.reason || `iteration ${item.iteration}`}</Text>
                  {item.output ? <Text numberOfLines={4} style={styles.output}>{item.output}</Text> : null}
                </View>
              )) : <Text style={styles.muted}>No specialist roles activated yet.</Text>}
            </Card>
          </View>

          <View style={styles.column}>
            <SectionTitle>Usage</SectionTitle>
            <Card style={styles.metrics}>
              <Metric label="Input tokens" value={totals.input.toLocaleString()} />
              <Metric label="Output tokens" value={totals.output.toLocaleString()} />
              <Metric label="Reported cost" value={`$${totals.cost.toFixed(4)}`} />
              <Metric label="Model calls" value={String(run.invocations.length)} />
            </Card>

            <SectionTitle>Execution</SectionTitle>
            <Card style={styles.stack}>
              {[...run.invocations].reverse().slice(0, 16).map((item, index) => (
                <View key={`${item.iteration}-${item.role}-${index}`} style={styles.row}>
                  <View>
                    <Text style={styles.rowLabel}>{item.role}</Text>
                    <Text style={styles.small}>{item.backend} · attempt {item.iteration}</Text>
                  </View>
                  <Text style={styles.rowValue}>{item.duration_seconds.toFixed(1)}s</Text>
                </View>
              ))}
            </Card>
          </View>
        </View>
      </ScrollView>
    </Screen>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <View style={styles.metric}><Text style={styles.small}>{label}</Text><Text style={styles.metricValue}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  shell: { padding: spacing.md, paddingBottom: 80, gap: spacing.lg, width: '100%', alignSelf: 'center' },
  shellWide: { maxWidth: 1360, padding: spacing.xl },
  hero: { gap: spacing.sm },
  heroTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  score: { color: palette.text, fontSize: 28, fontWeight: '900', fontVariant: ['tabular-nums'] },
  title: { color: palette.text, fontSize: 26, lineHeight: 33, fontWeight: '800', maxWidth: 920 },
  repo: { color: palette.muted, fontSize: 12 },
  columns: { gap: spacing.lg },
  columnsWide: { flexDirection: 'row', alignItems: 'flex-start' },
  column: { flex: 1, gap: spacing.sm, minWidth: 0 },
  stack: { gap: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md },
  rowRight: { flexDirection: 'row', gap: 6, alignItems: 'center' },
  rowLabel: { color: palette.text, fontSize: 14, fontWeight: '600' },
  rowValue: { color: palette.text, fontSize: 14, fontWeight: '800', fontVariant: ['tabular-nums'] },
  improved: { color: palette.good, fontWeight: '900' },
  evalRow: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md, alignItems: 'center' },
  flex: { flex: 1 },
  small: { color: palette.muted, fontSize: 12, lineHeight: 17 },
  agentBlock: { gap: 5, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: palette.border },
  agent: { color: palette.accent, textTransform: 'capitalize', fontWeight: '800' },
  reason: { color: palette.muted, fontSize: 12 },
  output: { color: palette.text, fontSize: 13, lineHeight: 18 },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  metric: { width: '47%', backgroundColor: palette.panelRaised, borderRadius: 13, padding: 12, gap: 4 },
  metricValue: { color: palette.text, fontSize: 18, fontWeight: '800', fontVariant: ['tabular-nums'] },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  muted: { color: palette.muted },
  error: { color: palette.bad },
});
