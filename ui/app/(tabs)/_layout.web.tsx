import { Tabs } from 'expo-router';
import { useWindowDimensions } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { AuthGate } from '@/components/auth-gate';
import { palette } from '@/lib/theme';

const DESKTOP_BREAKPOINT = 900;

export default function WebTabLayout() {
  const { width } = useWindowDimensions();
  const desktop = width >= DESKTOP_BREAKPOINT;

  return (
    <AuthGate>
      <Tabs
        screenOptions={{
          headerShown: false,
          sceneStyle: {
            backgroundColor: palette.bg,
            paddingBottom: desktop ? 0 : ('calc(60px + env(safe-area-inset-bottom))' as never),
          },
          tabBarActiveTintColor: palette.accent,
          tabBarInactiveTintColor: palette.muted,
          tabBarHideOnKeyboard: true,
          tabBarPosition: desktop ? 'left' : 'bottom',
          tabBarLabelPosition: desktop ? 'beside-icon' : 'below-icon',
          tabBarLabelStyle: {
            fontSize: desktop ? 13 : 11,
            fontWeight: '700',
            marginBottom: desktop ? 0 : 2,
          },
          tabBarItemStyle: desktop
            ? { minHeight: 48, maxHeight: 48, borderRadius: 10, marginHorizontal: 10, marginVertical: 2 }
            : { minHeight: 52, paddingTop: 5 },
          tabBarStyle: desktop
            ? {
                position: 'relative',
                width: 210,
                height: '100%',
                backgroundColor: palette.panel,
                borderRightColor: palette.border,
                borderRightWidth: 1,
                borderTopWidth: 0,
                paddingTop: 18,
                paddingBottom: 18,
              }
            : {
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 0,
                backgroundColor: palette.panel,
                borderTopColor: palette.border,
                borderTopWidth: 1,
                height: 'calc(60px + env(safe-area-inset-bottom))' as never,
                paddingBottom: 'max(6px, env(safe-area-inset-bottom))' as never,
                paddingHorizontal: 8,
              },
        }}
      >
        <Tabs.Screen name="index" options={{ title: 'Assistant', tabBarIcon: ({ color, size }) => <Feather name="message-circle" color={color as string} size={size} /> }} />
        <Tabs.Screen name="runs" options={{ title: 'Runs', tabBarIcon: ({ color, size }) => <Feather name="activity" color={color as string} size={size} /> }} />
        <Tabs.Screen name="benchmarks" options={{ title: 'Benchmarks', tabBarIcon: ({ color, size }) => <Feather name="bar-chart-2" color={color as string} size={size} /> }} />
        <Tabs.Screen name="settings" options={{ title: 'Settings', tabBarIcon: ({ color, size }) => <Feather name="settings" color={color as string} size={size} /> }} />
      </Tabs>
    </AuthGate>
  );
}
