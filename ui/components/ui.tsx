import { ReactNode } from 'react';
import { Pressable, StyleProp, StyleSheet, Text, View, ViewStyle } from 'react-native';
import { palette, spacing } from '@/lib/theme';

export function Screen({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.screen, style]}>{children}</View>;
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <Text style={styles.sectionTitle}>{children}</Text>;
}

export function Pill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  const color = tone === 'good' ? palette.good : tone === 'warn' ? palette.warn : tone === 'bad' ? palette.bad : palette.muted;
  return <View style={[styles.pill, { borderColor: color }]}><Text style={[styles.pillText, { color }]}>{label}</Text></View>;
}

export function PrimaryButton({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable disabled={disabled} onPress={onPress} style={({ pressed }) => [styles.button, disabled && styles.disabled, pressed && !disabled && styles.pressed]}>
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.bg },
  card: { backgroundColor: palette.panel, borderColor: palette.border, borderWidth: 1, borderRadius: 18, padding: spacing.md },
  sectionTitle: { color: palette.text, fontSize: 18, fontWeight: '700', marginBottom: spacing.sm },
  pill: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 9, paddingVertical: 4, alignSelf: 'flex-start' },
  pillText: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  button: { minHeight: 48, borderRadius: 14, backgroundColor: palette.accent, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 18 },
  buttonText: { color: '#08111f', fontWeight: '800', fontSize: 16 },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.8 },
});
