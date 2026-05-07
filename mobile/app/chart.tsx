import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, TouchableOpacity, StyleSheet, Linking, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';

const TV_SYMBOLS: Record<string, string> = {
  'EUR_USD': 'OANDA:EURUSD',
  'USD_JPY': 'OANDA:USDJPY',
  'GBP_USD': 'OANDA:GBPUSD',
  'MES': 'CME_MINI:MES1!',
  'ES': 'CME_MINI:ES1!',
  'SPY': 'AMEX:SPY',
  'QQQ': 'NASDAQ:QQQ',
};

function getTvUrl(instrument: string): string {
  const sym = TV_SYMBOLS[instrument] || instrument;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(sym)}`;
}

export default function ChartScreen() {
  const { symbol, interval, entry, exit, direction, stop, strategy } = useLocalSearchParams<{
    symbol: string; interval?: string; entry?: string; exit?: string; direction?: string; stop?: string; strategy?: string;
  }>();
  const router = useRouter();
  const tf = interval || '15m';
  const ticker = symbol || 'EUR_USD';

  // Build chart URL with optional trade lines
  let chartUrl = `${API_BASE}/chart?ticker=${encodeURIComponent(ticker)}&timespan=${tf}&count=300`;
  if (entry) chartUrl += `&entry=${entry}`;
  if (exit) chartUrl += `&exit=${exit}`;
  if (direction) chartUrl += `&direction=${direction}`;
  if (stop) chartUrl += `&stop=${stop}`;
  if (strategy) chartUrl += `&strategy=${strategy}`;

  const timespans = ticker === 'MES' || ticker === 'ES'
    ? [{ key: '2m', label: '2m' }]
    : [
        { key: '2m', label: '2m' },
        { key: '5m', label: '5m' },
        { key: '15m', label: '15m' },
        { key: '1h', label: '1H' },
        { key: '4h', label: '4H' },
        { key: '1d', label: '1D' },
      ];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>{ticker}</Text>
        <TouchableOpacity onPress={() => Linking.openURL(getTvUrl(ticker))} style={styles.tvBtn}>
          <Text style={styles.tvBtnText}>TV</Text>
        </TouchableOpacity>
        <View style={styles.tfRow}>
          {timespans.map(t => (
            <TouchableOpacity
              key={t.key}
              style={[styles.tfBtn, tf === t.key && styles.tfBtnActive]}
              onPress={() => router.setParams({ interval: t.key })}
            >
              <Text style={[styles.tfText, tf === t.key && styles.tfTextActive]}>
                {t.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
      <WebView
        key={`${ticker}-${tf}`}
        source={{ uri: chartUrl }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        renderLoading={() => <ActivityIndicator style={{ flex: 1, backgroundColor: '#1a1a2e' }} color={Colors.olive} />}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#1a1a2e' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 10,
    backgroundColor: '#1a1a2e',
    gap: 8,
  },
  backBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#333',
  },
  backText: { color: '#ccc', fontSize: 14 },
  title: { color: '#fff', fontSize: 16, fontWeight: '600', flex: 1 },
  tvBtn: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
    backgroundColor: '#1d4ed8',
  },
  tvBtnText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  tfRow: { flexDirection: 'row', gap: 4 },
  tfBtn: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
    backgroundColor: '#333',
  },
  tfBtnActive: { backgroundColor: Colors.olive },
  tfText: { color: '#999', fontSize: 12, fontWeight: '500' },
  tfTextActive: { color: Colors.gold },
  webview: { flex: 1 },
});
