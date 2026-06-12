import { useLocalSearchParams, Stack } from 'expo-router';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SwingTradePanel } from '@/components/swing-trade-panel';
import { Colors } from '@/constants/theme';

// Full-screen MTF / swing setup for a single ticker. Reached from the
// Multi-Timeframe scanner cards (Strategies tab) so you can analyze and
// place the options trade directly. The panel relies on a parent vertical
// ScrollView, mirroring how the Dashboard hosts it.
export default function SwingScreen() {
  const { ticker, mode } = useLocalSearchParams<{ ticker?: string; mode?: string }>();
  const m = (mode === 'scalp' || mode === 'intraday' || mode === 'swing')
    ? mode : 'swing';
  return (
    <SafeAreaView style={styles.root} edges={['left', 'right']}>
      <Stack.Screen
        options={{ title: ticker ? `${ticker} setup` : 'Swing Setup',
                   headerBackTitle: 'Back' }}
      />
      <ScrollView contentContainerStyle={styles.scroll}>
        <SwingTradePanel
          initialTicker={ticker ? String(ticker).toUpperCase() : undefined}
          initialMode={m}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.cream },
  scroll: { padding: 16, paddingBottom: 40 },
});
