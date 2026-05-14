import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl,
  TouchableOpacity, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
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
  eligible: boolean;
  atr_pct: number;
  drift_pips: number;
  fail_reason: string;
  since: string;
  anchor: string;
  history: RegimeHistoryEntry[];
};

type StrategyView = {
  name: string;
  universe: string[];
  eligible_count: number;
  total_count: number;
  pairs: Record<string, RegimePairState>;
};

function formatSince(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

function PairCard({ state, onPress }: { state: RegimePairState; onPress: () => void }) {
  const eligibilityColor = state.eligible ? Colors.green : Colors.red;
  return (
    <TouchableOpacity style={styles.pairCard} onPress={onPress}>
      <View style={styles.pairCardHeader}>
        <Text style={styles.pairName}>{state.pair}</Text>
        <View style={[styles.statusPill, { backgroundColor: eligibilityColor + '22' }]}>
          <Text style={[styles.statusText, { color: eligibilityColor }]}>
            {state.eligible ? '● ELIGIBLE' : '● PAUSED'}
          </Text>
        </View>
      </View>
      <View style={styles.metricsRow}>
        <Text style={styles.metric}>
          ATR <Text style={styles.metricValue}>{(state.atr_pct).toFixed(2)}%</Text>
        </Text>
        <Text style={styles.metric}>
          drift <Text style={styles.metricValue}>
            {state.drift_pips >= 0 ? '+' : ''}{state.drift_pips.toFixed(0)}p
          </Text>
        </Text>
      </View>
      <Text style={styles.sinceLine}>since {formatSince(state.since)}</Text>
      {!state.eligible && state.fail_reason ? (
        <Text style={styles.reasonLine}>⚠ {state.fail_reason}</Text>
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
  const [data, setData] = useState<Record<string, StrategyView> | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [drilledPair, setDrilledPair] = useState<RegimePairState | null>(null);

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
        <Text style={styles.title}>Strategies</Text>
        <Text style={styles.subtitle}>
          Pair eligibility recomputed every Sunday at the FX rollover
        </Text>

        {Object.entries(data).map(([sid, s]) => {
          const sortedPairs = s.universe
            .map(p => s.pairs[p])
            .filter(Boolean)
            // eligible first, then by pair name
            .sort((a, b) => {
              if (a.eligible !== b.eligible) return a.eligible ? -1 : 1;
              return a.pair.localeCompare(b.pair);
            });

          return (
            <View key={sid} style={styles.strategySection}>
              <View style={styles.strategyHeader}>
                <Text style={styles.strategyName}>{s.name}</Text>
                <Text style={styles.strategyCount}>
                  {s.eligible_count}/{s.total_count} ACTIVE
                </Text>
              </View>
              {sortedPairs.length === 0 ? (
                <Text style={styles.emptyText}>
                  No regime data yet — first run is scheduled for Sunday 17:00 ET.
                </Text>
              ) : (
                sortedPairs.map(p => (
                  <PairCard
                    key={p.pair}
                    state={p}
                    onPress={() => setDrilledPair(p)}
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
  strategySection: { marginBottom: 24 },
  strategyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  strategyName: { fontSize: 18, fontWeight: '600', color: Colors.dark },
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
