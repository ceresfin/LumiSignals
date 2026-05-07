import { useLocalSearchParams, useRouter } from 'expo-router';
import { View, Text, TouchableOpacity, StyleSheet, Linking, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';

// Full TradingView symbols for "Open in TV" button
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

// Level colors matching Pine Script
const LEVEL_COLORS = `{
  "M": { "supply": "#ff9800", "demand": "#ff9800", "label": "M" },
  "W": { "supply": "#ffeb3b", "demand": "#ffeb3b", "label": "W" },
  "D": { "supply": "#2196f3", "demand": "#2196f3", "label": "D" },
  "4H": { "supply": "#ce93d8", "demand": "#ce93d8", "label": "4H" },
  "1H": { "supply": "#66bb6a", "demand": "#66bb6a", "label": "1H" }
}`;

function buildChartHtml(ticker: string, timespan: string): string {
  // Strip underscore for levels API (EUR_USD → EURUSD)
  const levelsTicker = ticker.replace('_', '');

  return `<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #1a1a2e; overflow: hidden; }
    #chart { width: 100vw; height: 100vh; }
    #loading {
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      color: #888; font-family: -apple-system, sans-serif; font-size: 14px;
    }
    #error {
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      color: #c0392b; font-family: -apple-system, sans-serif; font-size: 14px;
      text-align: center; padding: 20px; display: none;
    }
  </style>
</head>
<body>
  <div id="chart"></div>
  <div id="loading">Loading chart...</div>
  <div id="error"></div>

  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <script>
    const API = '${API_BASE}';
    const TICKER = '${ticker}';
    const LEVELS_TICKER = '${levelsTicker}';
    const TIMESPAN = '${timespan}';
    const LEVEL_COLORS = ${LEVEL_COLORS};

    async function loadChart() {
      try {
        // Fetch candles
        const candleResp = await fetch(API + '/api/candles/' + TICKER + '?timespan=' + TIMESPAN + '&count=300');
        const candleData = await candleResp.json();

        if (!candleData.candles || candleData.candles.length === 0) {
          document.getElementById('loading').style.display = 'none';
          document.getElementById('error').style.display = 'block';
          document.getElementById('error').textContent = 'No candle data available for ' + TICKER;
          return;
        }

        // Create chart
        const chart = LightweightCharts.createChart(document.getElementById('chart'), {
          layout: {
            background: { color: '#1a1a2e' },
            textColor: '#888',
          },
          grid: {
            vertLines: { color: '#252547' },
            horzLines: { color: '#252547' },
          },
          crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
          },
          rightPriceScale: {
            borderColor: '#333',
          },
          timeScale: {
            borderColor: '#333',
            timeVisible: true,
            secondsVisible: false,
          },
        });

        // Add candlestick series
        const candleSeries = chart.addCandlestickSeries({
          upColor: '#27ae60',
          downColor: '#c0392b',
          borderDownColor: '#c0392b',
          borderUpColor: '#27ae60',
          wickDownColor: '#c0392b',
          wickUpColor: '#27ae60',
        });

        // Sort candles by time and remove duplicates
        const sorted = candleData.candles
          .filter(c => c.time > 0)
          .sort((a, b) => a.time - b.time);
        const unique = [];
        const seen = new Set();
        for (const c of sorted) {
          if (!seen.has(c.time)) {
            seen.add(c.time);
            unique.push(c);
          }
        }
        candleSeries.setData(unique);

        // Calculate and add VWAP line
        let vwapNum = 0, vwapDen = 0;
        const vwapData = [];
        for (const c of unique) {
          const hlc3 = (c.high + c.low + c.close) / 3;
          const vol = 1; // No volume data, use equal weight
          vwapNum += hlc3 * vol;
          vwapDen += vol;
          vwapData.push({ time: c.time, value: vwapNum / vwapDen });
        }
        const vwapSeries = chart.addLineSeries({
          color: '#ff6d00',
          lineWidth: 2,
          title: 'VWAP',
          priceLineVisible: false,
        });
        vwapSeries.setData(vwapData);

        // Fetch and overlay S/R levels
        try {
          const levelsResp = await fetch(API + '/api/levels/' + LEVELS_TICKER);
          const levelsData = await levelsResp.json();

          // Use TV levels first, fall back to server levels
          const levels = levelsData.tv && Object.keys(levelsData.tv).length > 0
            ? levelsData.tv
            : levelsData.server || {};

          for (const [tf, data] of Object.entries(levels)) {
            const colors = LEVEL_COLORS[tf];
            if (!colors) continue;

            // Supply (resistance) — line above price
            if (data.supply) {
              candleSeries.createPriceLine({
                price: data.supply,
                color: colors.supply,
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: colors.label + ' S1',
              });
            }

            // Demand (support) — line below price
            if (data.demand) {
              candleSeries.createPriceLine({
                price: data.demand,
                color: colors.demand,
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: colors.label + ' D1',
              });
            }
          }
        } catch (e) {
          console.log('Levels fetch error:', e);
        }

        // Fit content
        chart.timeScale().fitContent();

        // Handle resize
        const resizeObserver = new ResizeObserver(() => {
          chart.applyOptions({
            width: document.getElementById('chart').clientWidth,
            height: document.getElementById('chart').clientHeight,
          });
        });
        resizeObserver.observe(document.getElementById('chart'));

        document.getElementById('loading').style.display = 'none';

      } catch (err) {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('error').style.display = 'block';
        document.getElementById('error').textContent = 'Error: ' + err.message;
      }
    }

    loadChart();
  </script>
</body>
</html>`;
}

export default function ChartScreen() {
  const { symbol, interval } = useLocalSearchParams<{ symbol: string; interval?: string }>();
  const router = useRouter();
  const tf = interval || '15m';
  const ticker = symbol || 'EUR_USD';

  const html = buildChartHtml(ticker, tf);

  const timespans = ticker === 'MES' || ticker === 'ES'
    ? [{ key: '2m', label: '2m' }]  // IB only has 2m bars
    : [
        { key: '5m', label: '5m' },
        { key: '15m', label: '15m' },
        { key: '1h', label: '1H' },
        { key: '4h', label: '4H' },
        { key: '1d', label: '1D' },
      ];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
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
        source={{ html }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        renderLoading={() => <ActivityIndicator style={{ flex: 1 }} color={Colors.olive} />}
        originWhitelist={['*']}
        mixedContentMode="always"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#1a1a2e' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
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
