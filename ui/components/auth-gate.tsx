import { ReactNode, useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { api } from '@/lib/api';
import { palette, spacing } from '@/lib/theme';

export function AuthGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);

  const check = useCallback(async () => {
    try {
      const status = await api.authStatus();
      if (!status.authenticated) {
        router.replace('/login');
        return;
      }
      setReady(true);
    } catch {
      router.replace('/login');
    }
  }, []);

  useEffect(() => { void check(); }, [check]);
  useFocusEffect(useCallback(() => { void check(); }, [check]));

  if (!ready) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={palette.accent} />
        <Text style={styles.text}>Unlocking Avo…</Text>
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  loading: { flex: 1, backgroundColor: palette.bg, alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  text: { color: palette.muted, fontSize: 14 },
});
