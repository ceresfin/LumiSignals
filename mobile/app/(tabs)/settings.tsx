import { useEffect, useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView,
  Switch, Alert, ActivityIndicator, RefreshControl, Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Picker } from '@react-native-picker/picker';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

type Profile = Record<string, any>;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
      {hint ? <Text style={styles.fieldHint}>{hint}</Text> : null}
    </View>
  );
}

function NumberInput({ value, onChange, step = 1, min, max }: {
  value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number;
}) {
  return (
    <TextInput
      style={styles.input}
      value={String(value ?? '')}
      onChangeText={t => {
        const n = parseFloat(t) || 0;
        onChange(min !== undefined ? Math.max(min, max !== undefined ? Math.min(max, n) : n) : n);
      }}
      keyboardType="decimal-pad"
    />
  );
}

export default function Settings() {
  const { user, signOut } = useAuth();
  const [profile, setProfile] = useState<Profile>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [ibStatus, setIbStatus] = useState<{ connected: boolean; age_seconds?: number; nav?: number } | null>(null);

  const loadProfile = async () => {
    if (!user) return;
    const { data } = await supabase.from('profiles').select('*').eq('id', user.id).single();
    if (data) setProfile(data);
    setLoading(false);
  };

  const loadIbStatus = async () => {
    try {
      const resp = await fetch('https://bot.lumitrade.ai/api/ib/status');
      const data = await resp.json();
      setIbStatus(data);
    } catch {
      setIbStatus({ connected: false });
    }
  };

  useEffect(() => { loadProfile(); loadIbStatus(); }, [user]);
  // Refresh IB status every 30s
  useEffect(() => {
    const interval = setInterval(loadIbStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const update = (key: string, value: any) => {
    setProfile(prev => ({ ...prev, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    const { error } = await supabase.from('profiles').update(profile).eq('id', user!.id);
    setSaving(false);
    if (error) Alert.alert('Error', error.message);
    else Alert.alert('Saved', 'Settings updated');
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadProfile();
    setRefreshing(false);
  };

  if (loading) return (
    <SafeAreaView style={styles.container}>
      <ActivityIndicator style={{ marginTop: 40 }} color={Colors.olive} />
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Settings</Text>
          <TouchableOpacity style={styles.saveBtn} onPress={save} disabled={saving}>
            {saving ? <ActivityIndicator size="small" color={Colors.gold} /> :
              <Text style={styles.saveBtnText}>Save</Text>}
          </TouchableOpacity>
        </View>

        {/* Account */}
        <Section title="Account">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Email</Text>
            <Text style={styles.fieldValue}>{user?.email}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Plan</Text>
            <View style={styles.planBadge}>
              <Text style={styles.planText}>{profile.plan || 'free'}</Text>
            </View>
          </View>
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Bot Active</Text>
            <Switch value={profile.bot_active} onValueChange={v => update('bot_active', v)}
              trackColor={{ true: Colors.green }} />
          </View>
        </Section>

        {/* Broker — Oanda */}
        <Section title="1. Broker — Oanda">
          <Field label="Account ID" hint="101-001-xxxxx-001">
            <TextInput style={styles.input} value={profile.oanda_account_id || ''}
              onChangeText={t => update('oanda_account_id', t)} autoCapitalize="none" />
          </Field>
          <Field label="API Key">
            <TextInput style={styles.input} value={profile.oanda_api_key || ''}
              onChangeText={t => update('oanda_api_key', t)} secureTextEntry autoCapitalize="none" />
          </Field>
          <Field label="Environment">
            <View style={styles.pickerWrap}>
              <Picker selectedValue={profile.oanda_environment || 'practice'}
                onValueChange={v => update('oanda_environment', v)} style={styles.picker}>
                <Picker.Item label="Practice (Paper)" value="practice" />
                <Picker.Item label="Live" value="live" />
              </Picker>
            </View>
          </Field>
        </Section>

        {/* Strategy Settings */}
        {/* IB Gateway */}
        <Section title="IB Gateway">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Connection</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <View style={[styles.statusDot, { backgroundColor: ibStatus?.connected ? Colors.green : Colors.red }]} />
              <Text style={{ fontSize: 13, color: ibStatus?.connected ? Colors.green : Colors.red }}>
                {ibStatus?.connected
                  ? `Live (${ibStatus.age_seconds}s ago)`
                  : 'Disconnected'}
              </Text>
            </View>
          </View>
          {ibStatus?.connected && ibStatus.nav ? (
            <View style={styles.row}>
              <Text style={styles.fieldLabel}>NAV</Text>
              <Text style={styles.fieldValue}>${ibStatus.nav.toLocaleString('en-US', { minimumFractionDigits: 2 })}</Text>
            </View>
          ) : null}
          <TouchableOpacity
            style={styles.ibAuthButton}
            onPress={() => Linking.openURL('https://bot.lumitrade.ai/ib-vnc/vnc.html?autoconnect=true&resize=remote&password=lumisignals2026')}
          >
            <Text style={styles.ibAuthText}>Open IB Re-Auth (VNC)</Text>
          </TouchableOpacity>
          <Text style={styles.fieldHint}>Opens VNC in browser — no login needed. Click Login in the IB Gateway window.</Text>
        </Section>

        <Section title="2. Strategy Settings">
          {[
            { key: 'scalp', label: 'Scalp', color: Colors.scalp, zones: '1h + 4h', trigger: '15m' },
            { key: 'intraday', label: 'Intraday', color: Colors.intraday, zones: '4h + Daily', trigger: '1h' },
            { key: 'swing', label: 'Swing', color: Colors.swing, zones: 'W + M', trigger: 'Daily' },
          ].map(m => (
            <View key={m.key} style={[styles.modelSection, { borderLeftColor: m.color }]}>
              <Text style={[styles.modelLabel, { color: m.color }]}>{m.label}</Text>
              <Text style={styles.modelInfo}>{m.zones} zones, {m.trigger} trigger</Text>
              <View style={styles.modelRow}>
                <Field label="Min Score">
                  <NumberInput value={profile[`${m.key}_min_score`] ?? 50}
                    onChange={v => update(`${m.key}_min_score`, v)} min={0} max={100} step={5} />
                </Field>
                <Field label="Min R:R">
                  <NumberInput value={profile[`${m.key}_min_rr`] ?? 1.5}
                    onChange={v => update(`${m.key}_min_rr`, v)} min={0.5} max={10} step={0.1} />
                </Field>
              </View>
            </View>
          ))}
        </Section>

        {/* Risk Management */}
        <Section title="3. Position Sizing & Risk">
          {[
            { key: 'scalp', label: 'Scalp', defVal: 0.25 },
            { key: 'intraday', label: 'Intraday', defVal: 0.5 },
            { key: 'swing', label: 'Swing', defVal: 1.0 },
          ].map(m => (
            <View key={m.key} style={styles.riskSection}>
              <Text style={styles.riskLabel}>{m.label}</Text>
              <View style={styles.modelRow}>
                <Field label="Risk Mode">
                  <View style={styles.pickerWrap}>
                    <Picker selectedValue={profile[`${m.key}_risk_mode`] || 'percent'}
                      onValueChange={v => update(`${m.key}_risk_mode`, v)} style={styles.picker}>
                      <Picker.Item label="% of Account" value="percent" />
                      <Picker.Item label="Fixed $" value="fixed" />
                    </Picker>
                  </View>
                </Field>
                <Field label={profile[`${m.key}_risk_mode`] === 'fixed' ? 'Risk $' : 'Risk %'}>
                  <NumberInput value={profile[`${m.key}_risk_value`] ?? m.defVal}
                    onChange={v => update(`${m.key}_risk_value`, v)} min={0} step={0.01} />
                </Field>
                <Field label="Daily Limit $" hint="0 = unlimited">
                  <NumberInput value={profile[`${m.key}_daily_budget`] ?? 0}
                    onChange={v => update(`${m.key}_daily_budget`, v)} min={0} step={1} />
                </Field>
              </View>
            </View>
          ))}
        </Section>

        {/* Options */}
        <Section title="4. Options Auto-Trading">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Auto-trade on stock signals</Text>
            <Switch value={profile.options_auto_trade} onValueChange={v => update('options_auto_trade', v)}
              trackColor={{ true: Colors.green }} />
          </View>
          <View style={styles.modelRow}>
            <Field label="Max Risk/Spread $">
              <NumberInput value={profile.options_max_risk_per_spread ?? 200}
                onChange={v => update('options_max_risk_per_spread', v)} min={25} step={25} />
            </Field>
            <Field label="Max Contracts">
              <NumberInput value={profile.options_max_contracts ?? 5}
                onChange={v => update('options_max_contracts', v)} min={1} step={1} />
            </Field>
          </View>
          <View style={styles.modelRow}>
            <Field label="Spread Width $">
              <NumberInput value={profile.options_spread_width ?? 5}
                onChange={v => update('options_spread_width', v)} min={0.5} step={0.5} />
            </Field>
            <Field label="Options Trigger TF">
              <View style={styles.pickerWrap}>
                <Picker selectedValue={profile.options_trigger_tf || '4h'}
                  onValueChange={v => update('options_trigger_tf', v)} style={styles.picker}>
                  <Picker.Item label="15 min" value="15m" />
                  <Picker.Item label="1 hour" value="1h" />
                  <Picker.Item label="4 hour" value="4h" />
                  <Picker.Item label="Daily" value="1d" />
                </Picker>
              </View>
            </Field>
          </View>
        </Section>

        {/* Futures */}
        <Section title="5. Futures Settings">
          <View style={styles.modelRow}>
            <Field label="Stop Loss $" hint="Per contract">
              <NumberInput value={profile.futures_stop_loss ?? 25}
                onChange={v => update('futures_stop_loss', v)} min={5} step={5} />
            </Field>
            <Field label="Contracts/Entry">
              <NumberInput value={profile.futures_contracts ?? 1}
                onChange={v => update('futures_contracts', v)} min={1} step={1} />
            </Field>
          </View>
        </Section>

        {/* Sign Out */}
        <View style={styles.signOutSection}>
          <TouchableOpacity style={styles.signOutButton} onPress={() =>
            Alert.alert('Sign Out', 'Are you sure?', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Sign Out', style: 'destructive', onPress: signOut },
            ])
          }>
            <Text style={styles.signOutText}>Sign Out</Text>
          </TouchableOpacity>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 20, paddingTop: 12, paddingBottom: 12,
  },
  headerTitle: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  saveBtn: {
    backgroundColor: Colors.olive, paddingHorizontal: 20, paddingVertical: 10,
    borderRadius: 50,
  },
  saveBtnText: { color: Colors.gold, fontSize: 14, fontWeight: '600' },
  card: {
    backgroundColor: Colors.white, borderRadius: 12, padding: 16,
    marginHorizontal: 16, marginBottom: 12,
  },
  cardTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 14 },
  field: { marginBottom: 12 },
  fieldLabel: { fontSize: 13, fontWeight: '500', color: Colors.dark, marginBottom: 4 },
  fieldValue: { fontSize: 14, color: Colors.textLight },
  fieldHint: { fontSize: 11, color: Colors.textLight, marginTop: 2 },
  input: {
    backgroundColor: Colors.cream, borderRadius: 8, padding: 10,
    fontSize: 15, color: Colors.dark, borderWidth: 1, borderColor: '#e8e6e1',
  },
  pickerWrap: {
    backgroundColor: Colors.cream, borderRadius: 8, borderWidth: 1, borderColor: '#e8e6e1',
    overflow: 'hidden',
  },
  picker: { height: 44 },
  row: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#f5f3ee',
  },
  planBadge: {
    backgroundColor: Colors.olive, paddingHorizontal: 12, paddingVertical: 4, borderRadius: 50,
  },
  planText: { color: Colors.gold, fontSize: 12, fontWeight: '600' },
  modelSection: {
    borderLeftWidth: 3, paddingLeft: 12, marginBottom: 16,
  },
  modelLabel: { fontSize: 14, fontWeight: '700', marginBottom: 2 },
  modelInfo: { fontSize: 11, color: Colors.textLight, marginBottom: 8 },
  modelRow: { flexDirection: 'row', gap: 12 },
  riskSection: { marginBottom: 16, paddingTop: 12, borderTopWidth: 1, borderTopColor: '#f0f0f0' },
  riskLabel: { fontSize: 14, fontWeight: '600', color: Colors.dark, marginBottom: 8 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  ibAuthButton: {
    backgroundColor: Colors.olive, borderRadius: 10, padding: 14,
    alignItems: 'center', marginTop: 10,
  },
  ibAuthText: { color: Colors.gold, fontSize: 14, fontWeight: '600' },
  signOutSection: { paddingHorizontal: 16, marginTop: 8 },
  signOutButton: {
    backgroundColor: Colors.white, borderRadius: 12, padding: 16,
    alignItems: 'center', borderWidth: 1, borderColor: Colors.red,
  },
  signOutText: { color: Colors.red, fontSize: 15, fontWeight: '500' },
});
