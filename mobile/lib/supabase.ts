import { createClient } from '@supabase/supabase-js';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY!;

// SecureStore is iOS/Android only. During Metro's web/SSR pre-render the
// expo-secure-store JS wrapper still loads but calls a native function
// (getValueWithKeyAsync) that isn't exposed in the web shim — crashing the
// bundler at startup. Fall back to an in-memory no-op on web so the auth
// client can initialize cleanly. Native devices keep the keychain storage.
const isNative = Platform.OS === 'ios' || Platform.OS === 'android';

const SecureStoreAdapter = isNative
  ? {
      getItem: (key: string) => SecureStore.getItemAsync(key),
      setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
      removeItem: (key: string) => SecureStore.deleteItemAsync(key),
    }
  : {
      getItem: async (_key: string) => null as string | null,
      setItem: async (_key: string, _value: string) => {},
      removeItem: async (_key: string) => {},
    };

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    storage: SecureStoreAdapter,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false, // no browser redirects in RN
  },
});
