import { useEffect, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';
const POLL_MS = 15_000;

type Snapshot = {
  reconcileOk: boolean;
  ibConnected: boolean;
  killEnabled: boolean;
  killTripped: boolean;
  killDayPnl: number | null;
  killThreshold: number | null;
  runawayTripped: boolean;
  tradesToday: number | null;
  streak: number | null;
  accountType: 'paper' | 'live';
};

const DEFAULTS: Snapshot = {
  reconcileOk: true, ibConnected: true,
  killEnabled: true, killTripped: false,
  killDayPnl: null, killThreshold: null,
  runawayTripped: false, tradesToday: null, streak: null,
  accountType: 'paper',
};

export default function BotStatusCard() {
  const [s, setS] = useState<Snapshot>(DEFAULTS);

  const load = async () => {
    const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
    const next: Snapshot = { ...DEFAULTS };
    // All-in-one parallel fetch. Per-endpoint failure is ignored.
    await Promise.allSettled([
      fetch(`${API_BASE}/api/risk/reconcile-state`)
        .then(r => r.json())
        .then(d => { next.reconcileOk = !d?.locked; }),
      fetch(`${API_BASE}/api/ib/status`)
        .then(r => r.json())
        .then(d => { next.ibConnected = !!d?.connected; }),
      fetch(`${API_BASE}/api/risk/kill-switch`, { headers: { 'X-Sync-Key': syncKey } })
        .then(r => r.json())
        .then(d => {
          if (d?.config) {
            next.killEnabled = !!d.config.enabled;
            next.killThreshold = d.config.threshold_usd;
          }
          if (d?.state) {
            next.killTripped = !!d.state.tripped;
            next.killDayPnl = d.state.day_pnl;
          }
        }),
      fetch(`${API_BASE}/api/risk/runaway-guard`, { headers: { 'X-Sync-Key': syncKey } })
        .then(r => r.json())
        .then(d => {
          if (d?.state) {
            next.runawayTripped = !!d.state.tripped;
            next.tradesToday = d.state.trades_today;
            next.streak = d.state.consecutive_losses;
          }
        }),
      fetch(`${API_BASE}/api/risk/account-type`)
        .then(r => r.json())
        .then(d => { next.accountType = d?.account_type === 'live' ? 'live' : 'paper'; }),
    ]);
    setS(next);
  };

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, []);

  // Overall status: red if anything tripped/offline, amber if any warning, green otherwise.
  const tripped = !s.reconcileOk || !s.ibConnected || s.killTripped || s.runawayTripped;
  const hasLossStreak = (s.streak ?? 0) >= 2;  // warn before trip
  const accent = tripped ? Colors.red : hasLossStreak ? Colors.amber : Colors.green;
  const statusText = tripped ? 'ATTENTION' : hasLossStreak ? 'WATCH' : 'OK';

  return (
    <View style={[styles.card, { borderLeftColor: accent }]}>
      <View style={styles.row}>
        <View style={[styles.dot, { backgroundColor: accent }]} />
        <Text style={[styles.statusLabel, { color: accent }]}>{statusText}</Text>
        <Text style={styles.accountChip}>{s.accountType.toUpperCase()}</Text>
      </View>
      <View style={styles.grid}>
        <Stat label="Reconcile" value={s.reconcileOk ? 'OK' : 'LOCKED'}
              color={s.reconcileOk ? Colors.green : Colors.red} />
        <Stat label="IB" value={s.ibConnected ? 'Live' : 'Off'}
              color={s.ibConnected ? Colors.green : Colors.red} />
        <Stat label="Day P&L"
              value={s.killDayPnl == null ? '—' : `${s.killDayPnl >= 0 ? '+' : '-'}$${Math.abs(s.killDayPnl).toFixed(0)}`}
              color={s.killDayPnl == null ? Colors.textMedium
                     : s.killDayPnl >= 0 ? Colors.green : Colors.red} />
        <Stat label="Kill switch"
              value={s.killTripped ? 'TRIPPED' : s.killEnabled ? 'Armed' : 'Off'}
              color={s.killTripped ? Colors.red : s.killEnabled ? Colors.green : Colors.textMedium} />
        <Stat label="Trades today"
              value={s.tradesToday == null ? '—' : String(s.tradesToday)}
              color={s.runawayTripped ? Colors.red : Colors.dark} />
        <Stat label="Loss streak"
              value={s.streak == null ? '—' : String(s.streak)}
              color={s.runawayTripped ? Colors.red
                     : (s.streak ?? 0) >= 2 ? Colors.amber : Colors.dark} />
      </View>
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.white,
    marginHorizontal: 12,
    marginBottom: 12,
    padding: 12,
    borderRadius: 8,
    borderLeftWidth: 4,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  statusLabel: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  accountChip: {
    marginLeft: 'auto',
    fontSize: 10, fontWeight: '700', color: Colors.textMedium, letterSpacing: 0.5,
    backgroundColor: '#eceff1', paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4,
  },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  stat: { minWidth: 86 },
  statLabel: { fontSize: 10, color: Colors.textLight, marginBottom: 2 },
  statValue: { fontSize: 13, fontWeight: '600', fontVariant: ['tabular-nums'] },
});
