import { Tabs } from 'expo-router';
import { ColorValue, Text, useWindowDimensions } from 'react-native';
import { palette } from '@/lib/theme';

const icon = (symbol: string, color: ColorValue) => <Text style={{ color, fontSize: 18 }}>{symbol}</Text>;

export default function TabLayout() {
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: palette.bg },
        headerTintColor: palette.text,
        headerShadowVisible: false,
        tabBarStyle: {
          backgroundColor: palette.panel,
          borderTopColor: palette.border,
          height: wide ? 58 : 64,
          maxWidth: wide ? 720 : undefined,
          width: wide ? '100%' : undefined,
          alignSelf: wide ? 'center' : undefined,
        },
        tabBarActiveTintColor: palette.accent,
        tabBarInactiveTintColor: palette.muted,
        tabBarLabelStyle: { fontSize: 12, marginBottom: 6 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Runs', tabBarIcon: ({ color }) => icon('●', color) }} />
      <Tabs.Screen name="benchmarks" options={{ title: 'Benchmarks', tabBarIcon: ({ color }) => icon('▥', color) }} />
      <Tabs.Screen name="settings" options={{ title: 'Settings', tabBarIcon: ({ color }) => icon('⚙︎', color) }} />
    </Tabs>
  );
}
