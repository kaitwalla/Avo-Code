import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

export default function BenchmarksScreen() {
  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.shell}>
        <View style={styles.header}>
          <Text style={styles.title}>Benchmarks</Text>
          <Text style={styles.subtitle}>Harness quality and token efficiency stay visible here instead of disappearing into routing-policy JSON.</Text>
        </View>
        <Card style={styles.card}>
          <SectionTitle>Representative suite</SectionTitle>
          <View style={styles.grid}>
            <Metric label="Task families" value="5" />
            <Metric label="Strategies" value="8" />
            <Metric label="Default trials" value="80" />
            <Metric label="Selection" value="Quality first" />
          </View>
        </Card>
        <Card style={styles.card}>
          <SectionTitle>What this screen will surface</SectionTitle>
          <Text style={styles.body}>Solve rate, hidden-oracle score, tokens per solve, wall time, role overhead, cost, and the currently learned strategy for each task tag.</Text>
          <Text style={styles.note}>The first UI slice focuses on live task control. Benchmark report ingestion is the next API slice, using the report.json and routing-policy.json artifacts AvoGym already writes.</Text>
        </Card>
      </ScrollView>
    </Screen>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <View style={styles.metric}><Text style={styles.label}>{label}</Text><Text style={styles.value}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  shell: { width: '100%', maxWidth: 980, alignSelf: 'center', padding: spacing.md, paddingBottom: 90, gap: spacing.lg },
  header: { gap: 6, marginTop: spacing.sm },
  title: { color: palette.text, fontSize: 30, fontWeight: '800' },
  subtitle: { color: palette.muted, lineHeight: 21, maxWidth: 700 },
  card: { gap: spacing.md },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  metric: { minWidth: 145, flexGrow: 1, backgroundColor: palette.panelRaised, borderRadius: 14, padding: 14, gap: 4 },
  label: { color: palette.muted, fontSize: 12 },
  value: { color: palette.text, fontSize: 20, fontWeight: '800' },
  body: { color: palette.text, lineHeight: 22 },
  note: { color: palette.muted, fontSize: 13, lineHeight: 20 },
});
