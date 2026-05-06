import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef } from 'react';
import { AuthProvider, useAuth } from '@/contexts/auth';
import { registerForPushNotifications, addNotificationResponseListener } from '@/lib/notifications';

function AuthGate() {
  const { session, loading, user } = useAuth();
  const segments = useSegments();
  const router = useRouter();
  const notifRegistered = useRef(false);

  useEffect(() => {
    if (loading) return;
    const inAuthGroup = segments[0] === '(auth)';

    if (!session && !inAuthGroup) {
      router.replace('/(auth)/sign-in');
    } else if (session && inAuthGroup) {
      router.replace('/(tabs)');
    }
  }, [session, loading, segments]);

  // Register push notifications after sign-in
  useEffect(() => {
    if (user && !notifRegistered.current) {
      notifRegistered.current = true;
      registerForPushNotifications(user.id);
    }
  }, [user]);

  // Handle notification tap — navigate to trades
  useEffect(() => {
    const sub = addNotificationResponseListener((response) => {
      router.push('/(tabs)/trades');
    });
    return () => sub.remove();
  }, []);

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <AuthGate />
      <StatusBar style="dark" />
    </AuthProvider>
  );
}
