import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Colors } from '@/constants/theme';

// Map internal instrument names to TradingView symbols
const TV_SYMBOLS: Record<string, string> = {
  'EUR_USD': 'OANDA:EURUSD',
  'USD_JPY': 'OANDA:USDJPY',
  'GBP_USD': 'OANDA:GBPUSD',
  'USD_CHF': 'OANDA:USDCHF',
  'AUD_USD': 'OANDA:AUDUSD',
  'NZD_USD': 'OANDA:NZDUSD',
  'USD_CAD': 'OANDA:USDCAD',
  'MES': 'CME_MINI:MES1!',
  'ES': 'CME_MINI:ES1!',
  'SPY': 'AMEX:SPY',
  'QQQ': 'NASDAQ:QQQ',
  'AAPL': 'NASDAQ:AAPL',
  'MSFT': 'NASDAQ:MSFT',
  'NVDA': 'NASDAQ:NVDA',
  'TSLA': 'NASDAQ:TSLA',
  'AMZN': 'NASDAQ:AMZN',
  'META': 'NASDAQ:META',
  'GOOG': 'NASDAQ:GOOG',
  'AMD': 'NASDAQ:AMD',
  'JPM': 'NYSE:JPM',
  'DIS': 'NYSE:DIS',
  'BA': 'NYSE:BA',
};

function getTvSymbol(instrument: string): string {
  if (TV_SYMBOLS[instrument]) return TV_SYMBOLS[instrument];
  // Try common patterns
  if (instrument.includes('_')) {
    const pair = instrument.replace('_', '');
    return `OANDA:${pair}`;
  }
  return `NASDAQ:${instrument}`;
}

export default function ChartScreen() {
  const { symbol, interval } = useLocalSearchParams<{ symbol: string; interval?: string }>();
  const router = useRouter();

  const tvSymbol = getTvSymbol(symbol || 'EUR_USD');
  const tf = interval || '15';

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <style>
    * { margin: 0; padding: 0; }
    body { background: #1e1e1e; }
    #tv_chart { width: 100vw; height: 100vh; }
  </style>
</head>
<body>
  <div id="tv_chart"></div>
  <script src="https://s3.tradingview.com/tv.js"></script>
  <script>
    new TradingView.widget({
      "container_id": "tv_chart",
      "autosize": true,
      "symbol": "${tvSymbol}",
      "interval": "${tf}",
      "timezone": "America/New_York",
      "theme": "dark",
      "style": "1",
      "locale": "en",
      "toolbar_bg": "#1e1e1e",
      "enable_publishing": false,
      "hide_top_toolbar": false,
      "hide_legend": false,
      "save_image": false,
      "studies": ["VWAP@tv-basicstudies"],
      "show_popup_button": false,
      "popup_width": "1000",
      "popup_height": "650",
    });
  </script>
</body>
</html>`;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>{symbol}</Text>
        <View style={styles.tfRow}>
          {['5', '15', '60', 'D'].map(t => (
            <TouchableOpacity
              key={t}
              style={[styles.tfBtn, tf === t && styles.tfBtnActive]}
              onPress={() => router.setParams({ interval: t })}
            >
              <Text style={[styles.tfText, tf === t && styles.tfTextActive]}>
                {t === '60' ? '1H' : t === 'D' ? '1D' : `${t}m`}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
      <WebView
        source={{ html }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        originWhitelist={['*']}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#1e1e1e' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#1e1e1e',
    gap: 12,
  },
  backBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#333',
  },
  backText: { color: '#ccc', fontSize: 14 },
  title: { color: '#fff', fontSize: 16, fontWeight: '600', flex: 1 },
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
