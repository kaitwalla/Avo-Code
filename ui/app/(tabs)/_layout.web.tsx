import { Tabs } from 'expo-router';
import { useWindowDimensions } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { AuthGate } from '@/components/auth-gate';
import { palette } from '@/lib/theme';

export default function WebTabLayout() {
  const { width } = useWindowDimensions();
  const wide = width >= 900;

  return (
    <AuthGate>
      <Tabs
        screenOptions={{
          headerShown: false,
          sceneStyle: { backgroundColor: palette.bg },
          tabBarActiveTintColor: palette.accent,
          tabBarInactiveTintColor: palette.muted,
          tabBarHideOnKeyboard: true,
          tabBarLabelStyle: {
            fontSize: wide ? 12 : 11,
            fontWeight: '700',
            marginTop: 1,
            marginBottom: 2,
          },
          tabBarItemStyle: {
            minHeight: 52,
            paddingTop: 5,
          },
          tabBarStyle: {
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: palette.panel,
            borderTopColor: palette.border,
            borderTopWidth: 1,
            height: 'calc(60px + env(safe-area-inset-bottom))' as never,
            paddingBottom: 'max(6px, env(safe-area-inset-bottom))' as never,
            paddingHorizontal: wide ? 24 : 8,
            maxWidth: wide ? 760 : undefined,
            alignSelf: wide ? 'center' : undefined,
          },
        }}
      >
        <Tabs.Screen
          name="index"
          options={{
            title: 'Runs',
            tabBarIcon: ({ color, size }) => <Feather name="activity" color={color as string} size={size} />,
          }}
        />
        <Tabs.Screen
          name="benchmarks"
          options={{
            title: 'Benchmarks',
            tabBarIcon: ({ color, size }) => <Feather name="bar-chart-2" color={color as string} size={size} />,
          }}
        />
        <Tabs.Screen
          name="settings"
          options={{
            title: 'Settings',
            tabBarIcon: ({ color, size }) => <Feather name="settings" color={color as string} size={size} />,
          }}
        />
      </Tabs>
    </AuthGate>
  );
}
