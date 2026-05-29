import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
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
  const [resetting, setResetting] = useState(false);

  const onResetTap = () => {
    Alert.alert(
      'Reset reconcile gate?',
      'Webhooks will resume immediately. Only do this if you have verified broker positions match the bot state.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset', style: 'destructive', onPress: async () => {
            setResetting(true);
            try {
              const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
              const r = await fetch('https://bot.lumitrade.ai/api/risk/reconcile-state/reset', {
                method: 'POST',
                headers: { 'X-Sync-Key': syncKey },
              });
              if (r.ok) {
                setLocked(false);
                const d = await r.json();
                if (d?.state) setState(d.state);
              } else {
                Alert.alert('Reset failed', `HTTP ${r.status}`);
              }
            } catch (e: any) {
              Alert.alert('Reset failed', String(e?.message || e));
            } finally {
              setResetting(false);
            }
          },
        },
      ],
    );
  };

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
              ? 'New trades refused with 503. Tap Reset to resume once you have verified broker state.'
              : isReconciling
                ? 'Webhooks are being refused with 503 until the first sync pass finishes.'
                : (state.reason || 'No recent heartbeat from ibkr-sync. Waiting for it to come back up.')}
          </Text>
        </View>
        {isTimedOut ? (
          <TouchableOpacity
            style={[styles.resetBtn, resetting && { opacity: 0.5 }]}
            onPress={onResetTap}
            disabled={resetting}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Text style={styles.resetBtnText}>{resetting ? '…' : 'Reset'}</Text>
          </TouchableOpacity>
        ) : null}
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
  resetBtn: {
    backgroundColor: Colors.red,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  resetBtnText: { color: Colors.white, fontSize: 12, fontWeight: '600' },
});
