import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { api, ChatMessage, RunSummary } from '@/lib/api';
import { Card, Pill, Screen } from '@/components/ui';
import { palette, spacing } from '@/lib/theme';

function runTone(status: string) {
  if (status === 'accepted') return 'good' as const;
  if (status === 'running') return 'warn' as const;
  if (status === 'failed') return 'bad' as const;
  return 'neutral' as const;
}

function TaskCard({ run }: { run: RunSummary }) {
  return (
    <Pressable onPress={() => router.push(`/runs/${run.id}`)} style={({ pressed }) => pressed && { opacity: 0.78 }}>
      <Card style={styles.taskCard}>
        <View style={styles.taskTop}>
          <View style={styles.taskIdentity}>
            <Text style={styles.taskEyebrow}>CODING TASK</Text>
            <Text numberOfLines={2} style={styles.taskObjective}>{run.objective}</Text>
          </View>
          <Pill label={run.status} tone={runTone(run.status)} />
        </View>
        <View style={styles.taskBottom}>
          <Text style={styles.taskScore}>Score {Number(run.best_score ?? 0).toFixed(2)}</Text>
          <Text style={styles.taskLink}>Open details →</Text>
        </View>
      </Card>
    </Pressable>
  );
}

function PendingTaskCard({ objective }: { objective: string }) {
  return (
    <Card style={styles.taskCard}>
      <View style={styles.taskTop}>
        <View style={styles.taskIdentity}>
          <Text style={styles.taskEyebrow}>CODING TASK</Text>
          <Text numberOfLines={2} style={styles.taskObjective}>{objective || 'Preparing coding task'}</Text>
        </View>
        <Pill label="starting" tone="warn" />
      </View>
      <View style={styles.pendingRow}>
        <ActivityIndicator size="small" color={palette.accent} />
        <Text style={styles.taskScore}>Preparing baseline and isolated worktree…</Text>
      </View>
    </Card>
  );
}

function EvidenceBlock({ message }: { message: ChatMessage }) {
  const evidence = message.metadata?.evidence ?? [];
  if (!message.metadata?.execution_ready || evidence.length === 0) return null;
  return (
    <View style={styles.evidence}>
      <Text style={styles.evidenceTitle}>Why Avo was ready to act</Text>
      {evidence.slice(0, 3).map((item, index) => (
        <View key={`${item.source}-${index}`} style={styles.evidenceRow}>
          <Text style={styles.evidenceBullet}>•</Text>
          <View style={styles.evidenceCopy}>
            <Text style={styles.evidenceFact}>{item.fact}</Text>
            <Text numberOfLines={1} style={styles.evidenceSource}>{item.source}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const mine = message.role === 'user';
  if (message.status === 'thinking') {
    return (
      <View style={[styles.messageRow, styles.assistantRow]}>
        <View style={[styles.bubble, styles.assistantBubble, styles.thinkingBubble]}>
          <ActivityIndicator size="small" color={palette.accent} />
          <Text style={styles.thinkingText}>Avo is checking the repo…</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.messageRow, mine ? styles.userRow : styles.assistantRow]}>
      <View style={[styles.bubble, mine ? styles.userBubble : styles.assistantBubble]}>
        {!mine ? <Text style={styles.speaker}>AVO</Text> : null}
        <Text style={[styles.messageText, mine && styles.userText]}>{message.content}</Text>
        {!mine ? <EvidenceBlock message={message} /> : null}
        {message.run ? <TaskCard run={message.run} /> : null}
        {!message.run && message.kind === 'execution' ? (
          <PendingTaskCard objective={message.metadata?.objective ?? ''} />
        ) : null}
      </View>
    </View>
  );
}

export default function AssistantScreen() {
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setMessages(await api.chatMessages());
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));
  useEffect(() => {
    const timer = setInterval(() => void load(), 1600);
    return () => clearInterval(timer);
  }, [load]);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setDraft('');
    try {
      await api.sendChat(content, true);
      await load();
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDraft(content);
    } finally {
      setSending(false);
    }
  };

  return (
    <Screen>
      <KeyboardAvoidingView
        style={styles.keyboard}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 58 : 0}
      >
        <View style={[styles.shell, wide && styles.shellWide]}>
          <View style={[styles.header, wide && styles.headerWide]}>
            <View>
              <Text style={styles.eyebrow}>AVO</Text>
              <Text style={styles.title}>Engineering assistant</Text>
            </View>
            <Text style={styles.mode}>Investigates first · codes when ready</Text>
          </View>

          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(item) => item.id}
            renderItem={({ item }) => <MessageBubble message={item} />}
            contentContainerStyle={[styles.messages, messages.length === 0 && styles.messagesEmpty]}
            showsVerticalScrollIndicator={false}
            keyboardDismissMode="interactive"
            keyboardShouldPersistTaps="handled"
            onContentSizeChange={() => messages.length && listRef.current?.scrollToEnd({ animated: false })}
            ListEmptyComponent={(
              <View style={styles.welcome}>
                <Text style={styles.welcomeTitle}>Ask about the code. Or ask Avo to change it.</Text>
                <Text style={styles.welcomeText}>
                  Avo starts by investigating the repository. If the requested change is concrete and evidence-backed,
                  it will launch the coding loop automatically. If something important is ambiguous, it asks first.
                </Text>
                <View style={styles.prompts}>
                  <Text style={styles.prompt}>“Why is auth bouncing back to login?”</Text>
                  <Text style={styles.prompt}>“Fix the failing session refresh flow.”</Text>
                  <Text style={styles.prompt}>“How does the benchmark router decide which harness to use?”</Text>
                </View>
              </View>
            )}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={[styles.composer, wide && styles.composerWide]}>
            <TextInput
              value={draft}
              onChangeText={setDraft}
              placeholder="Message Avo…"
              placeholderTextColor={palette.muted}
              style={styles.input}
              multiline
              maxLength={12000}
              textAlignVertical="top"
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Send message"
              disabled={!draft.trim() || sending}
              onPress={send}
              style={({ pressed }) => [
                styles.send,
                (!draft.trim() || sending) && styles.sendDisabled,
                pressed && draft.trim() && !sending && styles.sendPressed,
              ]}
            >
              <Text style={styles.sendText}>{sending ? '…' : '↑'}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  keyboard: { flex: 1 },
  shell: { flex: 1, width: '100%', alignSelf: 'center', maxWidth: 920 },
  shellWide: { paddingHorizontal: spacing.xl },
  header: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: palette.border,
    gap: 3,
  },
  headerWide: { paddingHorizontal: 0, paddingTop: spacing.lg },
  eyebrow: { color: palette.accent, fontSize: 12, fontWeight: '900', letterSpacing: 1.7 },
  title: { color: palette.text, fontSize: 22, lineHeight: 28, fontWeight: '800' },
  mode: { color: palette.muted, fontSize: 12 },
  messages: { paddingHorizontal: spacing.md, paddingTop: spacing.lg, paddingBottom: spacing.md, gap: spacing.md },
  messagesEmpty: { flexGrow: 1, justifyContent: 'center' },
  messageRow: { width: '100%', flexDirection: 'row' },
  userRow: { justifyContent: 'flex-end' },
  assistantRow: { justifyContent: 'flex-start' },
  bubble: { maxWidth: '88%', borderRadius: 18, paddingHorizontal: 15, paddingVertical: 12, gap: 8 },
  userBubble: { backgroundColor: palette.accent },
  assistantBubble: { backgroundColor: palette.panel, borderWidth: 1, borderColor: palette.border },
  thinkingBubble: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  thinkingText: { color: palette.muted, fontSize: 14 },
  speaker: { color: palette.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1.3 },
  messageText: { color: palette.text, fontSize: 16, lineHeight: 23 },
  userText: { color: '#08111f', fontWeight: '600' },
  evidence: { marginTop: 4, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: palette.border, paddingTop: 10, gap: 7 },
  evidenceTitle: { color: palette.muted, fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.8 },
  evidenceRow: { flexDirection: 'row', gap: 7 },
  evidenceBullet: { color: palette.accent, fontSize: 15 },
  evidenceCopy: { flex: 1, gap: 2 },
  evidenceFact: { color: palette.text, fontSize: 13, lineHeight: 18 },
  evidenceSource: { color: palette.muted, fontSize: 11 },
  taskCard: { marginTop: 6, gap: 10, backgroundColor: '#111b2b' },
  taskTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  taskIdentity: { flex: 1, gap: 3 },
  taskEyebrow: { color: palette.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1.1 },
  taskObjective: { color: palette.text, fontSize: 14, lineHeight: 19, fontWeight: '700' },
  taskBottom: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  pendingRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  taskScore: { color: palette.muted, fontSize: 12 },
  taskLink: { color: palette.accent, fontSize: 12, fontWeight: '800' },
  welcome: { gap: spacing.md, paddingVertical: spacing.xl, maxWidth: 650 },
  welcomeTitle: { color: palette.text, fontSize: 27, lineHeight: 34, fontWeight: '800' },
  welcomeText: { color: palette.muted, fontSize: 15, lineHeight: 23 },
  prompts: { gap: 8, marginTop: 4 },
  prompt: { color: palette.text, fontSize: 13, lineHeight: 18, backgroundColor: palette.panel, borderRadius: 12, padding: 11 },
  error: { color: palette.bad, paddingHorizontal: spacing.md, paddingBottom: 6, fontSize: 12 },
  composer: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: palette.border,
    backgroundColor: palette.panel,
    borderRadius: 20,
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingLeft: 14,
    paddingRight: 7,
    paddingVertical: 7,
    gap: 8,
  },
  composerWide: { marginHorizontal: 0, marginBottom: spacing.lg },
  input: { flex: 1, minHeight: 42, maxHeight: 150, color: palette.text, fontSize: 16, lineHeight: 22, paddingTop: 9, paddingBottom: 8 },
  send: { width: 40, height: 40, borderRadius: 20, backgroundColor: palette.accent, alignItems: 'center', justifyContent: 'center' },
  sendDisabled: { opacity: 0.35 },
  sendPressed: { opacity: 0.78 },
  sendText: { color: '#08111f', fontSize: 22, lineHeight: 24, fontWeight: '900' },
});
