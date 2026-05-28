import { useEffect, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';
const POLL_MS = 5_000;

type ReconcileState = {
  status: 'ok' | 'reconciling' | 'timed_out';
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  timeout_at: string | null;
  last_heartbeat: string | null;
  reason: string | null;
};

export default function ReconcileBanner() {
  const [state, setState] = useState<ReconcileState | null>(null);
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/risk/reconcile-state`);
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        setState(d.state);
        setLocked(!!d.locked);
      } catch {
        // best-effort — leave previous state
      }
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Hide when unlocked (the common case).
  if (!locked || !state) return null;

  // Compute elapsed time since reconciliation started, for the reconciling case.
  let elapsedLabel = '';
  if (state.status === 'reconciling' && state.started_at) {
    try {
      const elapsed = Math.max(0, Math.round(
        (Date.now() - new Date(state.started_at).getTime()) / 1000,
      ));
      elapsedLabel = `${elapsed}s`;
    } catch { /* ignore */ }
  }

  const isTimedOut = state.status === 'timed_out';
  const isReconciling = state.status === 'reconciling';
  const isStaleOk = !isTimedOut && !isReconciling;

  return (
    <View style={[styles.banner, isTimedOut ? styles.bannerError : styles.bannerWarn]}>
      <View style={styles.row}>
        <View style={[styles.dot, isTimedOut ? styles.dotError : styles.dotWarn]} />
        <View style={{ flex: 1 }}>
          <Text style={[styles.title, isTimedOut ? styles.titleError : styles.titleWarn]}>
            {isTimedOut
              ? 'Reconciliation timed out'
              : isReconciling
                ? `Bot reconciling state${elapsedLabel ? ` · ${elapsedLabel}` : ''}`
                : 'Bot offline — webhooks blocked'}
          </Text>
          <Text style={styles.subtitle}>
            {isTimedOut
              ? 'New trades refused with 503. Open Settings → Reconcile gate → Reset to resume.'
              : isReconciling
                ? 'Webhooks are being refused with 503 until the first sync pass finishes.'
                : (state.reason || 'No recent heartbeat from ibkr-sync. Waiting for it to come back up.')}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderLeftWidth: 4,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginHorizontal: 12,
    marginTop: 8,
    borderRadius: 8,
  },
  bannerWarn: { backgroundColor: '#fff3e0', borderLeftColor: Colors.amber },
  bannerError: { backgroundColor: '#fdecea', borderLeftColor: Colors.red },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  dotWarn: { backgroundColor: Colors.amber },
  dotError: { backgroundColor: Colors.red },
  title: { fontSize: 13, fontWeight: '700' },
  titleWarn: { color: Colors.amber },
  titleError: { color: Colors.red },
  subtitle: { color: Colors.dark, fontSize: 11, marginTop: 2 },
});
