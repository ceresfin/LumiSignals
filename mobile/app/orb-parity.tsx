import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { Colors } from '@/constants/theme';
import { useResponsive } from '@/hooks/use-responsive';

const API = 'https://bot.lumitrade.ai/api/ibkr/orb';
const SYNC_KEY = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';

type NativeTrigger = {
  direction: string;
  entry: number;
  stop: number;
  target: number;
  reversal: boolean;
  traded: boolean;
  logged_at: string;
};
type TvAlert = {
  leg: string;
  direction: string;
  strategy: string;
  spread_type?: string;
  stop_price?: number;
  received_at: string;
};

function timeLabel(iso?: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function dirColor(dir: string): string {
  return dir?.includes('SELL') ? Colors.red : Colors.green;
}

export default function OrbParity() {
  const router = useRouter();
  const { contentStyle } = useResponsive();
  const [native, setNative] = useState<NativeTrigger[]>([]);
  const [tv, setTv] = useState<TvAlert[]>([]);
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([
        fetch(API + '/parity', { headers: { 'X-Sync-Key': SYNC_KEY } }).then((r) => r.json()),
        fetch(API + '/source', { headers: { 'X-Sync-Key': SYNC_KEY } }).then((r) => r.json()).catch(() => null),
      ]);
      setNative(p.native || []);
      setTv(p.tv || []);
      if (s?.source) setSource(s.source);
    } catch {
      // keep last data
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Text style={styles.back}>‹ Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>ORB — Native vs TradingView</Text>
        {source ? (
          <Text style={styles.source}>
            source: <Text style={{ color: source === 'native' ? Colors.green : Colors.textMedium }}>{source}</Text>
            {'   '}native {native.length} · TV {tv.length}
          </Text>
        ) : null}
      </View>

      {loading && !refreshing ? (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.olive} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={[{ paddingHorizontal: 16, paddingBottom: 28 }, contentStyle]}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
          <Text style={styles.sectionTitle}>Native triggers</Text>
          {native.length === 0 ? (
            <Text style={styles.empty}>None yet — ORB fires at the 9:45–11:00 ET open.</Text>
          ) : (
            native.map((n, i) => (
              <View key={'n' + i} style={styles.row}>
                <Text style={styles.time}>{timeLabel(n.logged_at)}</Text>
                <View style={[styles.badge, { backgroundColor: dirColor(n.direction) + '22' }]}>
                  <Text style={[styles.badgeText, { color: dirColor(n.direction) }]}>{n.direction}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cell}>
                    entry {n.entry} · stop {n.stop} · tgt {n.target}
                  </Text>
                  <Text style={styles.sub}>
                    {n.reversal ? 'reversal · ' : ''}
                    {n.traded ? 'traded' : 'shadow'}
                  </Text>
                </View>
              </View>
            ))
          )}

          <Text style={[styles.sectionTitle, { marginTop: 18 }]}>TradingView alerts</Text>
          {tv.length === 0 ? (
            <Text style={styles.empty}>No TV ORB alerts recorded yet.</Text>
          ) : (
            tv.map((t, i) => (
              <View key={'t' + i} style={styles.row}>
                <Text style={styles.time}>{timeLabel(t.received_at)}</Text>
                <View style={[styles.badge, { backgroundColor: dirColor(t.direction) + '22' }]}>
                  <Text style={[styles.badgeText, { color: dirColor(t.direction) }]}>{t.direction}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cell}>
                    {t.leg === 'butterfly' ? 'Butterfly' : 'MES'}
                    {t.spread_type ? ' · ' + t.spread_type : ''}
                    {t.stop_price ? ' · stop ' + t.stop_price : ''}
                  </Text>
                  <Text style={styles.sub}>{t.strategy}</Text>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 16, paddingTop: 6, paddingBottom: 6 },
  back: { color: Colors.olive, fontSize: 15, marginBottom: 4 },
  title: { fontSize: 22, fontWeight: '600', color: Colors.dark },
  source: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  center: { paddingTop: 50, alignItems: 'center' },
  sectionTitle: { fontSize: 13, fontWeight: '700', color: Colors.textMedium, marginTop: 8, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 },
  empty: { color: Colors.textLight, fontSize: 14, paddingVertical: 8 },
  row: {
    backgroundColor: Colors.white,
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  time: { fontSize: 13, fontWeight: '600', color: Colors.dark, width: 52 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8 },
  badgeText: { fontSize: 11, fontWeight: '700' },
  cell: { fontSize: 13, color: Colors.dark },
  sub: { fontSize: 11, color: Colors.textLight, marginTop: 2 },
});
