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

import { Colors } from '@/constants/theme';
import { useAuth } from '@/contexts/auth';
import { useResponsive } from '@/hooks/use-responsive';

const API = 'https://bot.lumitrade.ai/api/mtf-scan';

type ScanRow = {
  ticker: string;
  name?: string;
  asset_class: 'stock' | 'index' | 'fx' | 'crypto';
  group?: string;
  price: number | null;
  side: 'LONG' | 'SHORT';
  tf: string;
  level_name: string;
  level: number | null;
  dist_pct: number | null;
  vol_rank: number | null;
  vol_lean: string;
  suggested_spread: string;
  score: number;
  approx?: boolean;
};

type ScanResponse = {
  results: ScanRow[];
  warming?: boolean;
  stale?: boolean;
  scanned_at?: string | null;
  total?: number;
};

const GROUPS: { key: string; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'high_vol', label: 'High Vol' },
  { key: 'megacap', label: 'Megacap' },
  { key: 'largecap', label: 'Large' },
  { key: 'etf', label: 'ETF' },
  { key: 'index', label: 'Index' },
  { key: 'fx', label: 'FX' },
  { key: 'crypto', label: 'Crypto' },
];
const SIDES: { key: string; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'LONG', label: 'Long' },
  { key: 'SHORT', label: 'Short' },
];

const GROUP_LABEL: Record<string, string> = {
  high_vol: 'High Vol',
  megacap: 'Megacap',
  largecap: 'Large',
  etf: 'ETF',
  index: 'Index',
  fx: 'FX',
  crypto: 'Crypto',
};

function fmtNum(n: number | null): string {
  if (n == null) return '—';
  return n < 10 ? n.toFixed(4) : n.toFixed(2);
}

function VolDots({ rank }: { rank: number | null }) {
  if (!rank) return <Text style={styles.vol}>—</Text>;
  let dots = '';
  for (let i = 1; i <= 5; i++) dots += i <= rank ? '●' : '○';
  return (
    <Text style={styles.vol}>
      <Text style={{ color: Colors.olive }}>{dots}</Text> {rank}
    </Text>
  );
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.chip, active && styles.chipActive]}
      onPress={onPress}>
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

function Row({ item }: { item: ScanRow }) {
  const sideColor = item.side === 'LONG' ? Colors.green : Colors.red;
  const sideBg = item.side === 'LONG' ? '#e8f5e9' : '#fdecea';
  return (
    <View style={styles.row}>
      <View style={styles.rowTop}>
        <Text style={styles.ticker}>
          {item.approx ? '≈ ' : ''}
          {item.ticker}
        </Text>
        <Text style={styles.asset}>{GROUP_LABEL[item.group || ''] || item.asset_class}</Text>
        <View style={[styles.sideBadge, { backgroundColor: sideBg }]}>
          <Text style={[styles.sideText, { color: sideColor }]}>{item.side}</Text>
        </View>
        <View style={{ flex: 1 }} />
        <View
          style={[
            styles.scoreBadge,
            { backgroundColor: item.score >= 3 ? '#e8f5e9' : item.score >= 2 ? '#fff8e1' : '#f0f0f0' },
          ]}>
          <Text
            style={[
              styles.scoreText,
              { color: item.score >= 3 ? Colors.green : item.score >= 2 ? Colors.amber : Colors.textLight },
            ]}>
            {item.score}
          </Text>
        </View>
      </View>

      <View style={styles.rowMid}>
        <Text style={styles.priceLabel}>
          {fmtNum(item.price)}
          {item.name ? <Text style={styles.name}>  {item.name}</Text> : null}
        </Text>
      </View>

      <View style={styles.rowBottom}>
        <Text style={styles.cell}>
          <Text style={styles.dim}>{item.tf} </Text>
          {item.level_name} {fmtNum(item.level)}
        </Text>
        <Text style={styles.cell}>
          <Text style={styles.dim}>dist </Text>
          {item.dist_pct != null ? item.dist_pct.toFixed(2) + '%' : '—'}
        </Text>
        <VolDots rank={item.vol_rank} />
      </View>

      {item.suggested_spread && item.suggested_spread !== '—' ? (
        <Text style={styles.spread}>{item.suggested_spread}</Text>
      ) : null}
    </View>
  );
}

export default function Scanner() {
  const { user } = useAuth();
  const { contentStyle } = useResponsive();

  const [rows, setRows] = useState<ScanRow[]>([]);
  const [meta, setMeta] = useState<{ warming: boolean; stale: boolean; scannedAt: string | null }>({
    warming: false,
    stale: false,
    scannedAt: null,
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [group, setGroup] = useState('');
  const [side, setSide] = useState('');

  const load = useCallback(async () => {
    const qs: string[] = ['sort=dist'];
    if (group) qs.push('group=' + group);
    if (side) qs.push('side=' + side);
    try {
      const resp = await fetch(API + '?' + qs.join('&'));
      const data: ScanResponse = await resp.json();
      setRows(data.results || []);
      setMeta({
        warming: !!data.warming,
        stale: !!data.stale,
        scannedAt: data.scanned_at || null,
      });
    } catch {
      // keep last results on transient failure
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [group, side]);

  // Refetch on filter change.
  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  // Poll the cache every 60s.
  useEffect(() => {
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  const banner = (() => {
    if (meta.warming) return 'Scanner is warming up…';
    if (!meta.scannedAt) return '';
    const when = new Date(meta.scannedAt).toLocaleTimeString();
    return 'As of ' + when + (meta.stale ? ' (stale)' : '');
  })();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Scanner</Text>
        {banner ? (
          <Text style={[styles.banner, meta.stale && { color: Colors.red }]}>{banner}</Text>
        ) : null}
      </View>

      <View style={styles.filters}>
        <View style={styles.chipRow}>
          {GROUPS.map((g) => (
            <Chip key={g.key || 'all'} label={g.label} active={group === g.key} onPress={() => setGroup(g.key)} />
          ))}
        </View>
        <View style={styles.chipRow}>
          {SIDES.map((s) => (
            <Chip key={s.key || 'all'} label={s.label} active={side === s.key} onPress={() => setSide(s.key)} />
          ))}
        </View>
      </View>

      {loading && !refreshing ? (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.olive} />
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item, i) => item.ticker + ':' + item.tf + ':' + item.level_name + ':' + i}
          renderItem={({ item }) => <Row item={item} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          contentContainerStyle={[{ paddingHorizontal: 16, paddingBottom: 24 }, contentStyle]}
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.empty}>
                {meta.warming ? 'Building the first scan — check back shortly.' : 'No setups match these filters.'}
              </Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 4 },
  title: { fontSize: 26, fontWeight: '600', color: Colors.dark },
  banner: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  filters: { paddingHorizontal: 16, paddingTop: 6, paddingBottom: 8, gap: 6 },
  chipRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  chip: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 14,
    backgroundColor: '#F5F5F0',
    borderWidth: 1,
    borderColor: '#E0E0DA',
  },
  chipActive: { backgroundColor: Colors.olive, borderColor: Colors.olive },
  chipText: { fontSize: 12, fontWeight: '500', color: '#555' },
  chipTextActive: { color: Colors.white, fontWeight: '600' },
  center: { paddingTop: 60, alignItems: 'center' },
  empty: { color: Colors.textLight, fontSize: 14 },
  row: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  ticker: { fontSize: 16, fontWeight: '700', color: Colors.dark },
  asset: { fontSize: 11, color: Colors.textLight },
  sideBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8 },
  sideText: { fontSize: 11, fontWeight: '700' },
  scoreBadge: { paddingHorizontal: 9, paddingVertical: 2, borderRadius: 10 },
  scoreText: { fontSize: 12, fontWeight: '700' },
  rowMid: { marginTop: 6 },
  priceLabel: { fontSize: 14, fontWeight: '600', color: Colors.dark },
  name: { fontSize: 12, fontWeight: '400', color: Colors.textLight },
  rowBottom: { flexDirection: 'row', alignItems: 'center', marginTop: 6, gap: 16, flexWrap: 'wrap' },
  cell: { fontSize: 13, color: Colors.dark },
  dim: { color: Colors.textLight, fontSize: 12 },
  vol: { fontSize: 13, color: Colors.dark, letterSpacing: 1 },
  spread: { marginTop: 8, fontSize: 12, color: Colors.textMedium, fontStyle: 'italic' },
});
