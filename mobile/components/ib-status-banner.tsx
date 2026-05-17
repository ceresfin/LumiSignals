import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking } from 'react-native';
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
          onPress={() => Linking.openURL(`${API_BASE}/ib-auth`)}
          style={styles.btn}
        >
          <Text style={styles.btnText}>Reauth</Text>
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
