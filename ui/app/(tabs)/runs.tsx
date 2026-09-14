import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { api, RunSummary } from '@/lib/api';
import { Card, Pill, Screen } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

function tone(status: string) {
  if (status === 'accepted') return 'good' as const;
  if (status === 'running') return 'warn' as const;
  if (status === 'failed') return 'bad' as const;
  return 'neutral' as const;
}

function RunCard({ item }: { item: RunSummary }) {
  return (
    <Pressable onPress={() => router.push(`/runs/${item.id}`)} style={({ pressed }) => pressed && { opacity: 0.75 }}>
      <Card style={styles.card}>
        <View style={styles.top}>
          <Pill label={item.status} tone={tone(item.status)} />
          <Text style={styles.score}>{Number(item.best_score ?? 0).toFixed(2)}</Text>
        </View>
        <Text numberOfLines={3} style={styles.objective}>{item.objective}</Text>
        <Text numberOfLines={1} style={styles.repo}>{item.repo_path}</Text>
      </Card>
    </Pressable>
  );
}

export default function RunsScreen() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setRuns(await api.runs());
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useEffect(() => {
    const timer = setInterval(() => void load(), 3500);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <Screen>
      <FlatList
        data={runs}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={false} onRefresh={load} tintColor={palette.accent} />}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListHeaderComponent={(
          <View style={styles.header}>
            <Text style={styles.eyebrow}>ACTIVITY</Text>
            <Text style={styles.title}>Coding runs</Text>
            <Text style={styles.subtitle}>Avo launches these from conversation when a change is execution-ready.</Text>
            {error ? <Text style={styles.error}>{error}</Text> : null}
          </View>
        )}
        renderItem={({ item }) => <RunCard item={item} />}
        ListEmptyComponent={<Text style={styles.empty}>No coding runs yet. Ask Avo to make a change from the Assistant tab.</Text>}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: { width: '100%', maxWidth: 920, alignSelf: 'center', padding: spacing.md, paddingBottom: 110 },
  header: { gap: 5, marginBottom: spacing.lg, paddingTop: spacing.sm },
  eyebrow: { color: palette.accent, fontSize: 11, fontWeight: '900', letterSpacing: 1.5 },
  title: { color: palette.text, fontSize: 28, lineHeight: 34, fontWeight: '800' },
  subtitle: { color: palette.muted, fontSize: 14, lineHeight: 21, maxWidth: 640 },
  error: { color: palette.bad, fontSize: 12, marginTop: 4 },
  separator: { height: spacing.sm },
  card: { gap: 10 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  score: { color: palette.text, fontSize: 20, fontWeight: '800', fontVariant: ['tabular-nums'] },
  objective: { color: palette.text, fontSize: 16, lineHeight: 22, fontWeight: '600' },
  repo: { color: palette.muted, fontSize: 12 },
  empty: { color: palette.muted, textAlign: 'center', paddingVertical: 50, lineHeight: 20 },
});
