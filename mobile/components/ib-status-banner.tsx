import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking, Alert } from 'react-native';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';
const POLL_MS = 30_000;

type IbStatus = {
  connected: boolean;
  age_seconds: number | null;
  last_synced: string | null;
};

export default function IbStatusBanner() {
  const [status, setStatus] = useState<IbStatus | null>(null);
  const [reauthing, setReauthing] = useState(false);

  const loadStatus = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/ib/status`);
      const d = await r.json();
      setStatus(d);
    } catch {
      setStatus({ connected: false, age_seconds: null, last_synced: null });
    }
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/ib/status`);
        const d = await r.json();
        if (!cancelled) setStatus(d);
      } catch {
        if (!cancelled) setStatus({ connected: false, age_seconds: null, last_synced: null });
      }
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const handleReauth = async () => {
    if (reauthing) return;
    setReauthing(true);
    const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
    try {
      const r = await fetch(`${API_BASE}/api/ib/reauth`, {
        method: 'POST',
        headers: { 'X-Sync-Key': syncKey, 'Content-Type': 'application/json' },
      });
      const d = await r.json();
      if (r.ok && d?.ok) {
        Alert.alert('Reauth triggered', 'Session should be live in a few seconds.');
        // Poll status until connected or 30s elapses
        for (let i = 0; i < 15; i++) {
          await new Promise(res => setTimeout(res, 2000));
          await loadStatus();
        }
      } else {
        // IBeam likely has no session at all — fall back to the full
        // browser flow on bot.lumitrade.ai/ib-auth where the user can
        // log in via the proxied portal page.
        Alert.alert(
          'Reauth needs browser',
          'IBeam is fully signed out — opening the IB login page in Safari.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open', onPress: () => Linking.openURL(`${API_BASE}/ib-auth`) },
          ],
        );
      }
    } catch (e) {
      Alert.alert('Reauth failed', String(e));
    } finally {
      setReauthing(false);
    }
  };

  if (!status || status.connected) return null;

  const ageLabel = status.age_seconds != null
    ? `${Math.floor(status.age_seconds / 60)}m ago`
    : 'never';

  return (
    <View style={styles.banner}>
      <View style={styles.row}>
        <View style={styles.dot} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>IB sync offline</Text>
          <Text style={styles.subtitle}>Last sync: {ageLabel}. Orders are not being processed.</Text>
        </View>
        <TouchableOpacity
          onPress={handleReauth}
          disabled={reauthing}
          style={[styles.btn, reauthing && { opacity: 0.5 }]}
        >
          <Text style={styles.btnText}>{reauthing ? '…' : 'Reauth'}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    backgroundColor: '#fdecea',
    borderLeftWidth: 4,
    borderLeftColor: Colors.red,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginHorizontal: 12,
    marginTop: 8,
    borderRadius: 8,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Colors.red },
  title: { color: Colors.red, fontSize: 13, fontWeight: '700' },
  subtitle: { color: Colors.dark, fontSize: 11, marginTop: 2 },
  btn: {
    backgroundColor: Colors.red,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  btnText: { color: '#fff', fontSize: 12, fontWeight: '600' },
});
