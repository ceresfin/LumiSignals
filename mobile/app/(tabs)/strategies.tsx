import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  TouchableOpacity, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Colors } from '@/constants/theme';

// Each pair card shows: status, fingerprint metrics, since-when, reason
// when paused.  Tap → drill-in modal with the full flip history.
const API_BASE = 'https://bot.lumitrade.ai';

type RegimeHistoryEntry = {
  ts: string;
  eligible: boolean;
  atr_pct: number;
  drift_pips: number;
  fail_reason: string;
};

type RegimePairState = {
  pair: string;
  // Regime-strategy fields (Stillwater). All optional so the same shape
  // works for non-regime strategies (H1 Zone Scalp, Tidewater) which
  // only report active-trade or active-zone counts.
  eligible?: boolean;
  atr_pct?: number;
  drift_pips?: number;
  fail_reason?: string;
  since?: string;
  anchor?: string;
  history?: RegimeHistoryEntry[];
  // H1Zone fields
  pending_legs?: number;
  filled_legs?: number;
  // Tidewater (HTF Levels) fields
  hourly_zones?: number;
  daily_zones?: number;
  weekly_zones?: number;
  total_zones?: number;
};

type StrategyView = {
  name: string;
  subtitle?: string;
  description?: string;
  universe: string[];
  eligible_count: number;
  total_count: number;
  pairs: Record<string, RegimePairState>;
  // 'fx_4h' → regime card style; 'h1_zone' → H1 Zone Scalp card style
  chart_strategy?: string;
};

function formatSince(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

function PairCard({ state, onPress, onChart }: {
  state: RegimePairState;
  onPress: () => void;
  onChart?: () => void;
}) {
  const eligibilityColor = state.eligible ? Colors.green : Colors.red;
  return (
    <TouchableOpacity style={styles.pairCard} onPress={onPress}>
      <View style={styles.pairCardHeader}>
        <Text style={styles.pairName}>{state.pair}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={[styles.statusPill, { backgroundColor: eligibilityColor + '22' }]}>
            <Text style={[styles.statusText, { color: eligibilityColor }]}>
              {state.eligible ? '● ELIGIBLE' : '● PAUSED'}
            </Text>
          </View>
          {onChart ? (
            <TouchableOpacity onPress={(e) => { e.stopPropagation(); onChart(); }} style={styles.chartBtn}>
              <Text style={styles.chartBtnText}>chart</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>
      <View style={styles.metricsRow}>
        <Text style={styles.metric}>
          ATR <Text style={styles.metricValue}>{(state.atr_pct ?? 0).toFixed(2)}%</Text>
        </Text>
        <Text style={styles.metric}>
          drift <Text style={styles.metricValue}>
            {(state.drift_pips ?? 0) >= 0 ? '+' : ''}{(state.drift_pips ?? 0).toFixed(0)}p
          </Text>
        </Text>
      </View>
      {state.since ? <Text style={styles.sinceLine}>since {formatSince(state.since)}</Text> : null}
      {!state.eligible && state.fail_reason ? (
        <Text style={styles.reasonLine}>⚠ {state.fail_reason}</Text>
      ) : null}
    </TouchableOpacity>
  );
}

// Tidewater pair card — shows active zone counts across three durations
// (Hourly / Daily / Weekly). Card tap opens the chart with strategy=
// htf_levels so the chart's HTF overlay code path is used.
function TidewaterPairCard({ state, onChart }: {
  state: RegimePairState;
  onChart: () => void;
}) {
  const hourly = state.hourly_zones ?? 0;
  const daily = state.daily_zones ?? 0;
  const weekly = state.weekly_zones ?? 0;
  const total = state.total_zones ?? (hourly + daily + weekly);
  const isActive = total > 0;
  const pillColor = isActive ? Colors.green : '#666';
  return (
    <TouchableOpacity style={styles.pairCard} onPress={onChart}>
      <View style={styles.pairCardHeader}>
        <Text style={styles.pairName}>{state.pair}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={[styles.statusPill, { backgroundColor: pillColor + '22' }]}>
            <Text style={[styles.statusText, { color: pillColor }]}>
              {isActive ? `● ${total} ZONE${total > 1 ? 'S' : ''}` : '○ FLAT'}
            </Text>
          </View>
          <TouchableOpacity onPress={(e) => { e.stopPropagation(); onChart(); }} style={styles.chartBtn}>
            <Text style={styles.chartBtnText}>chart</Text>
          </TouchableOpacity>
        </View>
      </View>
      {isActive ? (
        <View style={styles.metricsRow}>
          <Text style={styles.metric}>
            hourly <Text style={styles.metricValue}>{hourly}</Text>
          </Text>
          <Text style={styles.metric}>
            daily <Text style={styles.metricValue}>{daily}</Text>
          </Text>
          <Text style={styles.metric}>
            weekly <Text style={styles.metricValue}>{weekly}</Text>
          </Text>
        </View>
      ) : null}
    </TouchableOpacity>
  );
}

// H1 Zone Scalp pair card — no regime state, just active-leg counts and
// a tap-to-chart affordance. Tapping the card OR the chart chip opens the
// chart for that pair with strategy=h1_zone.
function H1ZonePairCard({ state, onChart }: {
  state: RegimePairState;
  onChart: () => void;
}) {
  const pending = state.pending_legs ?? 0;
  const filled = state.filled_legs ?? 0;
  const active = pending + filled;
  const isActive = active > 0;
  const pillColor = isActive ? Colors.green : '#666';
  return (
    <TouchableOpacity style={styles.pairCard} onPress={onChart}>
      <View style={styles.pairCardHeader}>
        <Text style={styles.pairName}>{state.pair}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={[styles.statusPill, { backgroundColor: pillColor + '22' }]}>
            <Text style={[styles.statusText, { color: pillColor }]}>
              {isActive ? `● ${active} LEGS` : '○ FLAT'}
            </Text>
          </View>
          <TouchableOpacity onPress={(e) => { e.stopPropagation(); onChart(); }} style={styles.chartBtn}>
            <Text style={styles.chartBtnText}>chart</Text>
          </TouchableOpacity>
        </View>
      </View>
      {isActive ? (
        <View style={styles.metricsRow}>
          <Text style={styles.metric}>
            pending <Text style={styles.metricValue}>{pending}</Text>
          </Text>
          <Text style={styles.metric}>
            filled <Text style={styles.metricValue}>{filled}</Text>
          </Text>
        </View>
      ) : null}
    </TouchableOpacity>
  );
}

function HistoryModal({
  pair, visible, onClose,
}: {
  pair: RegimePairState | null;
  visible: boolean;
  onClose: () => void;
}) {
  if (!pair) return null;
  const reversed = [...pair.history].reverse();   // newest first
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet">
      <SafeAreaView style={styles.modalRoot}>
        <View style={styles.modalHeader}>
          <Text style={styles.modalTitle}>{pair.pair} regime history</Text>
          <TouchableOpacity onPress={onClose} style={styles.modalClose}>
            <Text style={styles.modalCloseText}>Done</Text>
          </TouchableOpacity>
        </View>
        <ScrollView contentContainerStyle={{ padding: 16 }}>
          {reversed.map((h, i) => {
            const color = h.eligible ? Colors.green : Colors.red;
            const prev = reversed[i + 1];
            const flipped = prev && prev.eligible !== h.eligible;
            return (
              <View key={`${h.ts}-${i}`} style={styles.historyRow}>
                <View style={[styles.historyDot, { backgroundColor: color }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.historyDate}>
                    {formatSince(h.ts)}
                    {flipped ? '  ← flip' : ''}
                  </Text>
                  <Text style={styles.historyDetail}>
                    <Text style={{ color, fontWeight: '600' }}>
                      {h.eligible ? 'ELIGIBLE' : 'PAUSED'}
                    </Text>
                    {'  ·  '}
                    ATR {h.atr_pct.toFixed(2)}%  ·  drift {h.drift_pips >= 0 ? '+' : ''}{h.drift_pips.toFixed(0)}p
                  </Text>
                  {!h.eligible && h.fail_reason ? (
                    <Text style={styles.historyReason}>{h.fail_reason}</Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

export default function Strategies() {
  const router = useRouter();
  const [data, setData] = useState<Record<string, StrategyView> | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [drilledPair, setDrilledPair] = useState<RegimePairState | null>(null);

  const openChart = useCallback((pair: string, chartStrategy: string) => {
    // chartStrategy gets passed through to mobile_chart.html so the
    // overlay code paths (H1Zone bundles, regime, etc.) light up correctly.
    // Default to 15m — the intermediate-trend TF that matters most for the
    // 5m-trigger H1 Zone Scalp; user can flip to 5m or 1H from the TF row.
    router.push({
      pathname: '/chart',
      params: { symbol: pair, strategy: chartStrategy, interval: '15m' },
    });
  }, [router]);

  const load = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/strategies/regime`);
      const json = await resp.json();
      setData(json.strategies || {});
    } catch (e) {
      console.warn('regime fetch failed', e);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  if (!data) {
    return (
      <SafeAreaView style={styles.root}>
        <Text style={styles.title}>Strategies</Text>
        <Text style={styles.subtitle}>Loading…</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <View style={styles.titleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Strategies</Text>
            <Text style={styles.subtitle}>
              Pair eligibility recomputed every Sunday at the FX rollover
            </Text>
          </View>
          <TouchableOpacity
            style={styles.compareBtn}
            onPress={() => router.push('/compare')}
          >
            <Text style={styles.compareBtnText}>Compare</Text>
          </TouchableOpacity>
        </View>

        {Object.entries(data).map(([sid, s]) => {
          const sortedPairs = s.universe
            .map(p => s.pairs[p])
            .filter(Boolean)
            // eligible first, then by pair name. For non-regime strategies
            // (eligible undefined) just sort alphabetically.
            .sort((a, b) => {
              const aE = a.eligible, bE = b.eligible;
              if (aE !== undefined && bE !== undefined && aE !== bE) {
                return aE ? -1 : 1;
              }
              return a.pair.localeCompare(b.pair);
            });

          return (
            <View key={sid} style={styles.strategySection}>
              <View style={styles.strategyHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.strategyName}>{s.name}</Text>
                  {s.subtitle ? (
                    <Text style={styles.strategySubtitle}>{s.subtitle}</Text>
                  ) : null}
                </View>
                <Text style={styles.strategyCount}>
                  {s.eligible_count}/{s.total_count} ACTIVE
                </Text>
              </View>
              {s.description ? (
                <Text style={styles.strategyDescription}>{s.description}</Text>
              ) : null}
              {sortedPairs.length === 0 ? (
                <Text style={styles.emptyText}>
                  {s.chart_strategy === 'h1_zone'
                    ? 'No pairs configured yet.'
                    : 'No regime data yet — first run is scheduled for Sunday 17:00 ET.'}
                </Text>
              ) : s.chart_strategy === 'h1_zone' ? (
                sortedPairs.map(p => (
                  <H1ZonePairCard
                    key={p.pair}
                    state={p}
                    onChart={() => openChart(p.pair, 'h1_zone')}
                  />
                ))
              ) : s.chart_strategy === 'htf_levels' ? (
                sortedPairs.map(p => (
                  <TidewaterPairCard
                    key={p.pair}
                    state={p}
                    onChart={() => openChart(p.pair, 'htf_levels')}
                  />
                ))
              ) : (
                sortedPairs.map(p => (
                  <PairCard
                    key={p.pair}
                    state={p}
                    onPress={() => setDrilledPair(p)}
                    onChart={() => openChart(p.pair, s.chart_strategy || sid)}
                  />
                ))
              )}
            </View>
          );
        })}
      </ScrollView>

      <HistoryModal
        pair={drilledPair}
        visible={drilledPair !== null}
        onClose={() => setDrilledPair(null)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.cream },
  scroll: { padding: 16, paddingBottom: 40 },
  title: { fontSize: 26, fontWeight: '700', color: Colors.dark },
  subtitle: { fontSize: 13, color: Colors.textLight, marginTop: 4, marginBottom: 16 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-start' },
  compareBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1d4ed8', marginTop: 6 },
  compareBtnText: { color: '#fff', fontSize: 12, fontWeight: '700', letterSpacing: 0.4 },
  strategySection: { marginBottom: 24 },
  strategyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  strategyName: { fontSize: 20, fontWeight: '700', color: Colors.dark, letterSpacing: 0.3 },
  strategySubtitle: {
    fontSize: 11, fontWeight: '600', color: Colors.textLight,
    letterSpacing: 0.7, textTransform: 'uppercase', marginTop: 2,
  },
  strategyDescription: {
    fontSize: 13, lineHeight: 19, color: Colors.textMedium,
    marginBottom: 12, marginTop: 4,
  },
  strategyCount: {
    fontSize: 12, fontWeight: '700', color: Colors.olive,
    letterSpacing: 0.5,
  },
  pairCard: {
    backgroundColor: Colors.white,
    borderRadius: 10,
    padding: 14,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#eee',
  },
  pairCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  pairName: { fontSize: 16, fontWeight: '600', color: Colors.dark, letterSpacing: 0.5 },
  statusPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 12 },
  statusText: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  chartBtn: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: '#1d4ed8' },
  chartBtnText: { color: '#fff', fontSize: 10, fontWeight: '700', letterSpacing: 0.4, textTransform: 'uppercase' },
  metricsRow: { flexDirection: 'row', gap: 16, marginBottom: 4 },
  metric: { fontSize: 13, color: Colors.textLight },
  metricValue: { color: Colors.dark, fontWeight: '600' },
  sinceLine: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  reasonLine: { fontSize: 12, color: Colors.red, marginTop: 4 },
  emptyText: { fontSize: 13, color: Colors.textLight, fontStyle: 'italic' },

  modalRoot: { flex: 1, backgroundColor: Colors.cream },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    backgroundColor: Colors.white,
  },
  modalTitle: { fontSize: 17, fontWeight: '600', color: Colors.dark },
  modalClose: { padding: 4 },
  modalCloseText: { color: Colors.olive, fontSize: 16, fontWeight: '600' },
  historyRow: {
    flexDirection: 'row',
    gap: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  historyDot: { width: 10, height: 10, borderRadius: 5, marginTop: 6 },
  historyDate: { fontSize: 14, fontWeight: '600', color: Colors.dark },
  historyDetail: { fontSize: 13, color: Colors.textLight, marginTop: 2 },
  historyReason: { fontSize: 12, color: Colors.red, marginTop: 2 },
});
