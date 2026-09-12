import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { Card, Pill, Screen, SectionTitle } from '@/components/ui';
import { api, BenchmarkDetail, BenchmarkSummary, StrategyChoice, VariantMetrics } from '@/lib/api';
import { palette, spacing } from '@/lib/theme';

function percent(value?: number) {
  return value == null ? '—' : `${Math.round(value * 100)}%`;
}

function number(value?: number | null, digits = 0) {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function seconds(value?: number) {
  if (value == null) return '—';
  if (value < 60) return `${value.toFixed(1)}s`;
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
}

function strategyTone(name: string, selected?: string) {
  return name === selected ? 'good' as const : 'neutral' as const;
}

export default function BenchmarksScreen() {
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const [summaries, setSummaries] = useState<BenchmarkSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BenchmarkDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (refresh = false) => {
    refresh ? setRefreshing(true) : setLoading(true);
    setError('');
    try {
      const list = await api.benchmarks();
      setSummaries(list);
      const id = selectedId && list.some((item) => item.id === selectedId) ? selectedId : list[0]?.id ?? null;
      setSelectedId(id);
      setDetail(id ? await api.benchmark(id) : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedId]);

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const select = useCallback(async (id: string) => {
    setSelectedId(id);
    setLoading(true);
    setError('');
    try {
      setDetail(await api.benchmark(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const variants = useMemo(
    () => Object.entries(detail?.report.variants ?? {}).sort((a, b) => {
      const solve = (b[1].oracle_solve_rate ?? 0) - (a[1].oracle_solve_rate ?? 0);
      if (solve) return solve;
      return (a[1].mean_total_tokens ?? Number.POSITIVE_INFINITY) - (b[1].mean_total_tokens ?? Number.POSITIVE_INFINITY);
    }),
    [detail],
  );
  const policy = detail?.routing_policy;
  const defaultChoice = policy?.default ?? null;
  const tagChoices = Object.entries(policy?.by_tag ?? {});

  return (
    <Screen>
      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void load(true)} tintColor={palette.accent} />}
        contentContainerStyle={styles.shell}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Benchmarks</Text>
          <Text style={styles.subtitle}>Hidden-oracle quality first. Tokens, latency, and cost only break quality ties.</Text>
        </View>

        {error ? <Card style={styles.errorCard}><Text style={styles.errorText}>{error}</Text></Card> : null}

        {loading && !detail ? <View style={styles.loading}><ActivityIndicator color={palette.accent} /></View> : null}

        {!loading && summaries.length === 0 ? (
          <Card style={styles.card}>
            <SectionTitle>No benchmark reports yet</SectionTitle>
            <Text style={styles.body}>Run AvoGym with an output directory beneath the configured benchmark root. This screen discovers report.json and routing-policy.json automatically.</Text>
            <Text style={styles.note}>Set AVO_BENCHMARK_ROOT if your reports live somewhere else.</Text>
          </Card>
        ) : null}

        {summaries.length > 0 ? (
          <View style={[styles.topGrid, wide && styles.topGridWide]}>
            <Card style={[styles.card, wide && styles.historyCard]}>
              <SectionTitle>Benchmark runs</SectionTitle>
              <View style={styles.historyList}>
                {summaries.map((item) => (
                  <Pressable key={item.id} onPress={() => void select(item.id)} style={({ pressed }) => [styles.historyItem, item.id === selectedId && styles.historyItemSelected, pressed && styles.pressed]}>
                    <View style={styles.historyText}>
                      <Text style={styles.historyTitle} numberOfLines={1}>{item.experiment}</Text>
                      <Text style={styles.historyMeta}>{item.trial_count} trials · {item.variant_count} strategies</Text>
                    </View>
                    {item.default_strategy ? <Pill label={item.default_strategy} tone="good" /> : null}
                  </Pressable>
                ))}
              </View>
            </Card>

            {detail ? (
              <Card style={[styles.card, wide && styles.policyCard]}>
                <View style={styles.sectionRow}>
                  <SectionTitle>Learned routing</SectionTitle>
                  <Pill label={policy?.selection ?? 'quality first'} tone="good" />
                </View>
                {defaultChoice ? <ChoiceCard label="Default" choice={defaultChoice} /> : <Text style={styles.note}>No routing decision was produced.</Text>}
                {tagChoices.length ? (
                  <View style={styles.tagGrid}>
                    {tagChoices.map(([tag, choice]) => <ChoiceCard compact key={tag} label={tag} choice={choice} />)}
                  </View>
                ) : null}
              </Card>
            ) : null}
          </View>
        ) : null}

        {detail ? (
          <Card style={styles.card}>
            <View style={styles.sectionRow}>
              <View>
                <SectionTitle>Strategy comparison</SectionTitle>
                <Text style={styles.note}>{detail.report.experiment ?? selectedId}</Text>
              </View>
              {loading ? <ActivityIndicator color={palette.accent} /> : null}
            </View>
            <View style={styles.variantGrid}>
              {variants.map(([name, metrics], index) => (
                <VariantCard
                  key={name}
                  name={name}
                  metrics={metrics}
                  rank={index + 1}
                  selected={defaultChoice?.variant === name}
                  wide={wide}
                />
              ))}
            </View>
          </Card>
        ) : null}
      </ScrollView>
    </Screen>
  );
}

function ChoiceCard({ label, choice, compact = false }: { label: string; choice: StrategyChoice; compact?: boolean }) {
  return (
    <View style={[styles.choice, compact && styles.choiceCompact]}>
      <Text style={styles.choiceLabel}>{label}</Text>
      <Text style={styles.choiceName} numberOfLines={1}>{choice.variant}</Text>
      <View style={styles.choiceEvidence}>
        <Text style={styles.choiceMetric}>{percent(choice.solve_rate)} solve</Text>
        <Text style={styles.choiceMetric}>{number(choice.mean_tokens)} tok</Text>
        <Text style={styles.choiceMetric}>{seconds(choice.mean_wall_seconds)}</Text>
      </View>
    </View>
  );
}

function VariantCard({ name, metrics, rank, selected, wide }: { name: string; metrics: VariantMetrics; rank: number; selected: boolean; wide: boolean }) {
  return (
    <View style={[styles.variant, wide && styles.variantWide, selected && styles.variantSelected]}>
      <View style={styles.variantHeader}>
        <View style={styles.rank}><Text style={styles.rankText}>{rank}</Text></View>
        <Text style={styles.variantName} numberOfLines={2}>{name}</Text>
        <Pill label={selected ? 'default' : percent(metrics.oracle_solve_rate)} tone={strategyTone(name, selected ? name : undefined)} />
      </View>
      <View style={styles.metricsGrid}>
        <Metric label="Solve" value={percent(metrics.oracle_solve_rate)} />
        <Metric label="Oracle" value={metrics.mean_oracle_score == null ? '—' : metrics.mean_oracle_score.toFixed(3)} />
        <Metric label="Tokens / solve" value={number(metrics.tokens_per_oracle_solve)} />
        <Metric label="Mean tokens" value={number(metrics.mean_total_tokens)} />
        <Metric label="Wall time" value={seconds(metrics.mean_wall_seconds)} />
        <Metric label="Role calls" value={number(metrics.mean_role_invocations, 1)} />
      </View>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <View style={styles.metric}><Text style={styles.label}>{label}</Text><Text style={styles.value}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  shell: { width: '100%', maxWidth: 1180, alignSelf: 'center', padding: spacing.md, paddingBottom: 90, gap: spacing.lg },
  header: { gap: 6, marginTop: spacing.sm },
  title: { color: palette.text, fontSize: 30, fontWeight: '800' },
  subtitle: { color: palette.muted, lineHeight: 21, maxWidth: 760 },
  card: { gap: spacing.md },
  loading: { paddingVertical: 40 },
  errorCard: { borderColor: palette.bad },
  errorText: { color: palette.bad, lineHeight: 20 },
  body: { color: palette.text, lineHeight: 22 },
  note: { color: palette.muted, fontSize: 13, lineHeight: 20 },
  topGrid: { gap: spacing.lg },
  topGridWide: { flexDirection: 'row', alignItems: 'flex-start' },
  historyCard: { width: 360 },
  policyCard: { flex: 1 },
  historyList: { gap: spacing.sm },
  historyItem: { minHeight: 62, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.panelRaised, borderRadius: 14, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 10 },
  historyItemSelected: { borderColor: palette.accent },
  pressed: { opacity: 0.76 },
  historyText: { flex: 1, gap: 4 },
  historyTitle: { color: palette.text, fontWeight: '700' },
  historyMeta: { color: palette.muted, fontSize: 12 },
  sectionRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.sm },
  choice: { backgroundColor: palette.panelRaised, borderRadius: 16, padding: 15, gap: 5, borderWidth: 1, borderColor: palette.good },
  choiceCompact: { flexGrow: 1, minWidth: 165, borderColor: palette.border },
  choiceLabel: { color: palette.muted, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  choiceName: { color: palette.text, fontSize: 18, fontWeight: '800' },
  choiceEvidence: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  choiceMetric: { color: palette.muted, fontSize: 12 },
  tagGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  variantGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  variant: { width: '100%', backgroundColor: palette.panelRaised, borderRadius: 16, padding: 14, gap: 14, borderWidth: 1, borderColor: palette.border },
  variantWide: { width: '48.8%', flexGrow: 1 },
  variantSelected: { borderColor: palette.good },
  variantHeader: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  rank: { width: 28, height: 28, borderRadius: 9, backgroundColor: palette.panel, justifyContent: 'center', alignItems: 'center' },
  rankText: { color: palette.muted, fontWeight: '800', fontSize: 12 },
  variantName: { color: palette.text, fontSize: 16, fontWeight: '800', flex: 1 },
  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  metric: { minWidth: 96, flexGrow: 1, backgroundColor: palette.panel, borderRadius: 12, padding: 10, gap: 3 },
  label: { color: palette.muted, fontSize: 11 },
  value: { color: palette.text, fontSize: 16, fontWeight: '800' },
});
