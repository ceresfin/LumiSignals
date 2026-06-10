import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { Colors } from '@/constants/theme';
import { useResponsive } from '@/hooks/use-responsive';

const API = 'https://bot.lumitrade.ai/api/ibkr/mes-2n20';
const SYNC_KEY = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';

type Row = {
  bar_time: number;
  kind: string;
  native_dir: string | null;
  tv_dir: string | null;
  native_traded: boolean;
  status: 'agree' | 'native_only' | 'tv_only';
};
type Summary = {
  agree: number;
  native_only: number;
  tv_only: number;
  native_total: number;
  tv_total: number;
};

const STATUS_COLOR: Record<string, string> = {
  agree: Colors.green,
  native_only: Colors.amber,
  tv_only: Colors.red,
};
const STATUS_LABEL: Record<string, string> = {
  agree: 'agree',
  native_only: 'native only',
  tv_only: 'TV only',
};

function barTimeLabel(t: number): string {
  if (!t) return '—';
  try {
    return new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return String(t);
  }
}

function dirColor(dir: string | null): string {
  if (!dir) return Colors.textLight;
  return dir.includes('SELL') || dir === 'CLOSE_LONG' ? Colors.red : Colors.green;
}

export default function MesParity() {
  const router = useRouter();
  const { contentStyle } = useResponsive();
  const [rows, setRows] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [source, setSource] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([
        fetch(API + '/parity', { headers: { 'X-Sync-Key': SYNC_KEY } }).then((r) => r.json()),
        fetch(API + '/source', { headers: { 'X-Sync-Key': SYNC_KEY } }).then((r) => r.json()).catch(() => null),
      ]);
      setRows(p.rows || []);
      setSummary(p.summary || null);
      if (s?.source) setSource(s.source);
    } catch {
      // keep last data on transient failure
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
        <Text style={styles.title}>2n20 — Native vs TradingView</Text>
        {source ? (
          <Text style={styles.source}>
            source: <Text style={{ color: source === 'native' ? Colors.green : Colors.textMedium }}>{source}</Text>
          </Text>
        ) : null}
      </View>

      {summary ? (
        <View style={[styles.summaryRow, contentStyle]}>
          <Stat label="Agree" value={summary.agree} color={Colors.green} />
          <Stat label="Native only" value={summary.native_only} color={Colors.amber} />
          <Stat label="TV only" value={summary.tv_only} color={Colors.red} />
        </View>
      ) : null}

      {loading && !refreshing ? (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.olive} />
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(r, i) => r.bar_time + ':' + r.kind + ':' + i}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Text style={styles.time}>{barTimeLabel(item.bar_time)}</Text>
              <Text style={styles.kind}>{item.kind}</Text>
              <View style={styles.dirs}>
                <Text style={styles.dirLabel}>N</Text>
                <Text style={[styles.dir, { color: dirColor(item.native_dir) }]}>{item.native_dir || '—'}</Text>
                <Text style={styles.dirLabel}>  TV</Text>
                <Text style={[styles.dir, { color: dirColor(item.tv_dir) }]}>{item.tv_dir || '—'}</Text>
              </View>
              <View style={[styles.badge, { backgroundColor: STATUS_COLOR[item.status] + '22' }]}>
                <Text style={[styles.badgeText, { color: STATUS_COLOR[item.status] }]}>
                  {STATUS_LABEL[item.status]}
                </Text>
              </View>
            </View>
          )}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          contentContainerStyle={[{ paddingHorizontal: 16, paddingBottom: 24 }, contentStyle]}
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.empty}>
                No signals yet — they appear as native fires and TradingView alerts arrive.
              </Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 16, paddingTop: 6, paddingBottom: 6 },
  back: { color: Colors.olive, fontSize: 15, marginBottom: 4 },
  title: { fontSize: 22, fontWeight: '600', color: Colors.dark },
  source: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  summaryRow: { flexDirection: 'row', paddingHorizontal: 16, paddingVertical: 10, gap: 10 },
  stat: {
    flex: 1,
    backgroundColor: Colors.white,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
  },
  statValue: { fontSize: 24, fontWeight: '700' },
  statLabel: { fontSize: 11, color: Colors.textLight, marginTop: 2 },
  center: { paddingTop: 50, alignItems: 'center', paddingHorizontal: 24 },
  empty: { color: Colors.textLight, fontSize: 14, textAlign: 'center' },
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
  kind: { fontSize: 11, color: Colors.textLight, width: 42 },
  dirs: { flex: 1, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap' },
  dirLabel: { fontSize: 11, color: Colors.textLight },
  dir: { fontSize: 12, fontWeight: '600', marginLeft: 3 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8 },
  badgeText: { fontSize: 11, fontWeight: '700' },
});
