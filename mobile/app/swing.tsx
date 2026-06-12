import { useLocalSearchParams, useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SwingTradePanel } from '@/components/swing-trade-panel';
import { Colors } from '@/constants/theme';

// Full-screen MTF / swing setup for a single ticker. Reached from the
// Multi-Timeframe scanner cards (Strategies tab) so you can analyze and
// place the options trade directly. The root Stack hides the native header
// (headerShown:false), so — like compare/mes-parity — we draw our own Back
// row. The panel relies on a parent vertical ScrollView.
export default function SwingScreen() {
  const router = useRouter();
  const { ticker, mode } = useLocalSearchParams<{ ticker?: string; mode?: string }>();
  const m = (mode === 'scalp' || mode === 'intraday' || mode === 'swing')
    ? mode : 'swing';
  const tkr = ticker ? String(ticker).toUpperCase() : undefined;
  return (
    <SafeAreaView style={styles.root} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Text style={styles.back}>‹ Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>{tkr ? `${tkr} setup` : 'Swing Setup'}</Text>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        <SwingTradePanel initialTicker={tkr} initialMode={m} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 6 },
  back: { color: Colors.olive, fontSize: 15, marginBottom: 4 },
  title: { fontSize: 22, fontWeight: '600', color: Colors.dark },
  scroll: { padding: 16, paddingBottom: 40 },
});
