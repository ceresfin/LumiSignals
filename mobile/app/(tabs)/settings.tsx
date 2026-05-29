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
  const [reauthing, setReauthing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [ibStatus, setIbStatus] = useState<{ connected: boolean; age_seconds?: number; nav?: number } | null>(null);
  // Daily-loss kill switch — config + live state.
  const [killCfg, setKillCfg] = useState<{
    enabled: boolean; threshold_usd: number;
    reset_hour_et: number; reset_minute_et: number;
  }>({ enabled: true, threshold_usd: 250, reset_hour_et: 9, reset_minute_et: 30 });
  const [killState, setKillState] = useState<{
    tripped: boolean; tripped_at: string | null; day_pnl: number;
    day_start: string | null; reason: string | null;
  }>({ tripped: false, tripped_at: null, day_pnl: 0, day_start: null, reason: null });
  const [killSaving, setKillSaving] = useState(false);
  const [killResetting, setKillResetting] = useState(false);
  // Position size guard
  const [pgCfg, setPgCfg] = useState<{
    enabled: boolean; default_limit: number; limits: Record<string, number>;
  }>({ enabled: true, default_limit: 2, limits: {} });
  const [pgPositions, setPgPositions] = useState<Record<string, number>>({});
  const [pgSaving, setPgSaving] = useState(false);
  // Reconcile gate (restart-safety lock)
  const [rgState, setRgState] = useState<{
    status: 'ok' | 'reconciling' | 'timed_out';
    duration_seconds: number | null;
    last_heartbeat: string | null;
    reason: string | null;
  }>({ status: 'ok', duration_seconds: null, last_heartbeat: null, reason: null });
  const [rgLocked, setRgLocked] = useState(false);
  const [rgResetting, setRgResetting] = useState(false);
  const [flattening, setFlattening] = useState(false);

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

  const loadKillSwitch = async () => {
    try {
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/kill-switch', {
        headers: { 'X-Sync-Key': syncKey },
      });
      if (!r.ok) return;
      const d = await r.json();
      if (d?.config) setKillCfg(d.config);
      if (d?.state) setKillState(d.state);
    } catch {
      // best-effort; keep current values
    }
  };

  const saveKillSwitch = async (patch: Partial<typeof killCfg>) => {
    setKillSaving(true);
    try {
      const next = { ...killCfg, ...patch };
      setKillCfg(next); // optimistic
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/kill-switch', {
        method: 'PUT',
        headers: { 'X-Sync-Key': syncKey, 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (d?.config) setKillCfg(d.config);
      if (d?.state) setKillState(d.state);
    } catch (e: any) {
      Alert.alert('Kill switch save failed', String(e?.message || e));
    } finally {
      setKillSaving(false);
    }
  };

  const resetKillSwitch = async () => {
    setKillResetting(true);
    try {
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/kill-switch/reset', {
        method: 'POST',
        headers: { 'X-Sync-Key': syncKey },
      });
      const d = await r.json();
      if (d?.state) setKillState(d.state);
    } catch (e: any) {
      Alert.alert('Reset failed', String(e?.message || e));
    } finally {
      setKillResetting(false);
    }
  };

  const loadPositionGuard = async () => {
    try {
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/position-guard', {
        headers: { 'X-Sync-Key': syncKey },
      });
      if (!r.ok) return;
      const d = await r.json();
      if (d?.config) setPgCfg(d.config);
      if (d?.positions) setPgPositions(d.positions);
    } catch {
      // best-effort
    }
  };

  const savePositionGuard = async (patch: Partial<typeof pgCfg>) => {
    setPgSaving(true);
    try {
      const next = { ...pgCfg, ...patch };
      setPgCfg(next); // optimistic
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/position-guard', {
        method: 'PUT',
        headers: { 'X-Sync-Key': syncKey, 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (d?.config) setPgCfg(d.config);
      if (d?.positions) setPgPositions(d.positions);
    } catch (e: any) {
      Alert.alert('Position guard save failed', String(e?.message || e));
    } finally {
      setPgSaving(false);
    }
  };

  const loadReconcileGate = async () => {
    try {
      const r = await fetch('https://bot.lumitrade.ai/api/risk/reconcile-state');
      if (!r.ok) return;
      const d = await r.json();
      if (d?.state) setRgState(d.state);
      setRgLocked(!!d.locked);
    } catch {
      // best-effort
    }
  };

  const resetReconcileGate = async () => {
    setRgResetting(true);
    try {
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/reconcile-state/reset', {
        method: 'POST',
        headers: { 'X-Sync-Key': syncKey },
      });
      const d = await r.json();
      if (d?.state) setRgState(d.state);
      setRgLocked(false);
    } catch (e: any) {
      Alert.alert('Reset failed', String(e?.message || e));
    } finally {
      setRgResetting(false);
    }
  };

  const flattenAll = async () => {
    setFlattening(true);
    try {
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
      const r = await fetch('https://bot.lumitrade.ai/api/risk/flatten-all', {
        method: 'POST',
        headers: { 'X-Sync-Key': syncKey },
      });
      const d = await r.json();
      if (r.ok && d?.status === 'queued') {
        const lines = (d.queued || []).map(
          (o: any) => `${o.ticker} ${o.qty > 0 ? 'long' : 'short'} ${Math.abs(o.qty)}`,
        ).join('\n');
        Alert.alert(
          `Flatten queued: ${d.count} position(s)`,
          lines || 'Already flat — no positions to close.',
        );
      } else {
        Alert.alert('Flatten failed', d?.detail || d?.reason || `HTTP ${r.status}`);
      }
    } catch (e: any) {
      Alert.alert('Flatten failed', String(e?.message || e));
    } finally {
      setFlattening(false);
    }
  };

  useEffect(() => {
    loadProfile(); loadIbStatus(); loadKillSwitch(); loadPositionGuard(); loadReconcileGate();
  }, [user]);
  // Poll reconcile gate every 5s so the Settings screen reflects state quickly.
  useEffect(() => {
    const id = setInterval(loadReconcileGate, 5000);
    return () => clearInterval(id);
  }, []);
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
    await Promise.all([loadProfile(), loadIbStatus(), loadKillSwitch(), loadPositionGuard()]);
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
            style={[styles.ibAuthButton, reauthing && { opacity: 0.5 }]}
            disabled={reauthing}
            onPress={async () => {
              if (reauthing) return;
              setReauthing(true);
              const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
              try {
                const r = await fetch('https://bot.lumitrade.ai/api/ib/reauth', {
                  method: 'POST',
                  headers: { 'X-Sync-Key': syncKey, 'Content-Type': 'application/json' },
                });
                const d = await r.json();
                if (r.ok && d?.ok) {
                  Alert.alert('Reauth triggered', 'Session should be live in a few seconds.');
                  // Poll IB status until connected or 30 s elapses
                  for (let i = 0; i < 15; i++) {
                    await new Promise(res => setTimeout(res, 2000));
                    try {
                      const sr = await fetch('https://bot.lumitrade.ai/api/ib/status');
                      const sd = await sr.json();
                      setIbStatus(sd);
                      if (sd?.connected) break;
                    } catch {}
                  }
                } else {
                  Alert.alert(
                    'Reauth needs browser',
                    'IBeam is fully signed out — opening the IB login page in Safari.',
                    [
                      { text: 'Cancel', style: 'cancel' },
                      { text: 'Open', onPress: () => Linking.openURL('https://bot.lumitrade.ai/ib-auth') },
                    ],
                  );
                }
              } catch (e: any) {
                Alert.alert('Reauth failed', String(e?.message || e));
              } finally {
                setReauthing(false);
              }
            }}
          >
            <Text style={styles.ibAuthText}>{reauthing ? 'Reauthenticating…' : 'Re-authenticate IB'}</Text>
          </TouchableOpacity>
          <Text style={styles.fieldHint}>Refreshes the IBeam session in-place. If IBeam is fully signed out, you'll get a prompt to open the browser login.</Text>
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

        {/* Daily-Loss Kill Switch */}
        <Section title="6. Daily Loss Kill Switch">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Enabled</Text>
            <Switch
              value={killCfg.enabled}
              onValueChange={v => saveKillSwitch({ enabled: v })}
              disabled={killSaving}
              trackColor={{ true: Colors.green }}
            />
          </View>
          <Field label="Threshold $" hint="Bot refuses new entries when day P&L ≤ −threshold">
            <TextInput
              style={styles.input}
              value={String(killCfg.threshold_usd ?? 250)}
              onChangeText={t => setKillCfg({ ...killCfg, threshold_usd: parseFloat(t) || 0 })}
              onEndEditing={() => saveKillSwitch({ threshold_usd: killCfg.threshold_usd })}
              keyboardType="decimal-pad"
              editable={!killSaving}
            />
          </Field>
          <Field label="Reset at (ET)" hint="Hour:minute when day P&L resets">
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <TextInput
                style={[styles.input, { width: 64, textAlign: 'center' }]}
                value={String(killCfg.reset_hour_et ?? 9)}
                onChangeText={t => setKillCfg({ ...killCfg, reset_hour_et: parseInt(t, 10) || 0 })}
                onEndEditing={() => saveKillSwitch({ reset_hour_et: killCfg.reset_hour_et })}
                keyboardType="number-pad"
                editable={!killSaving}
              />
              <Text style={{ fontSize: 16, color: Colors.dark }}>:</Text>
              <TextInput
                style={[styles.input, { width: 64, textAlign: 'center' }]}
                value={String(killCfg.reset_minute_et ?? 30).padStart(2, '0')}
                onChangeText={t => setKillCfg({ ...killCfg, reset_minute_et: parseInt(t, 10) || 0 })}
                onEndEditing={() => saveKillSwitch({ reset_minute_et: killCfg.reset_minute_et })}
                keyboardType="number-pad"
                editable={!killSaving}
              />
            </View>
          </Field>
          <View style={[styles.row, { marginTop: 4 }]}>
            <Text style={styles.fieldLabel}>Today's realized P&L</Text>
            <Text style={[
              styles.fieldValue,
              { color: killState.day_pnl >= 0 ? Colors.green : Colors.red, fontWeight: '600' },
            ]}>
              {killState.day_pnl >= 0 ? '+' : '-'}${Math.abs(killState.day_pnl).toFixed(2)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Status</Text>
            <Text style={[
              styles.fieldValue,
              { color: killState.tripped ? Colors.red : (killCfg.enabled ? Colors.green : Colors.textMedium),
                fontWeight: '600' },
            ]}>
              {killState.tripped ? 'TRIPPED — new entries blocked'
                : killCfg.enabled ? 'Armed' : 'Disabled'}
            </Text>
          </View>
          {killState.tripped && killState.reason ? (
            <Text style={[styles.fieldHint, { color: Colors.red, marginTop: 4 }]}>
              {killState.reason}
            </Text>
          ) : null}
          {killState.tripped ? (
            <TouchableOpacity
              style={[styles.ibAuthButton, { backgroundColor: Colors.red, marginTop: 12 },
                      killResetting && { opacity: 0.5 }]}
              onPress={() =>
                Alert.alert(
                  'Reset kill switch?',
                  'New entries will resume immediately. Day P&L stays at its current value — next loss can re-trip.',
                  [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Reset', style: 'destructive', onPress: resetKillSwitch },
                  ],
                )
              }
              disabled={killResetting}
            >
              <Text style={styles.ibAuthText}>
                {killResetting ? 'Resetting…' : 'Reset kill switch'}
              </Text>
            </TouchableOpacity>
          ) : null}
          <Text style={styles.fieldHint}>
            Blocks new BUY/SELL entries when day P&L crosses the threshold.
            Closes still process so existing positions exit normally.
            Bracket SL at IB stays in place as the per-trade safety net.
          </Text>
        </Section>

        {/* Position Size Guard */}
        <Section title="7. Position Size Guard">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Enabled</Text>
            <Switch
              value={pgCfg.enabled}
              onValueChange={v => savePositionGuard({ enabled: v })}
              disabled={pgSaving}
              trackColor={{ true: Colors.green }}
            />
          </View>
          <Field label="Max contracts per instrument" hint="Bot refuses entries that would push |net position| past this">
            <TextInput
              style={styles.input}
              value={String(pgCfg.default_limit ?? 2)}
              onChangeText={t => setPgCfg({ ...pgCfg, default_limit: parseInt(t, 10) || 0 })}
              onEndEditing={() => savePositionGuard({ default_limit: pgCfg.default_limit })}
              keyboardType="number-pad"
              editable={!pgSaving}
            />
          </Field>
          <View style={[styles.row, { marginTop: 4 }]}>
            <Text style={styles.fieldLabel}>Current positions</Text>
            <Text style={[styles.fieldValue, { fontWeight: '600' }]}>
              {Object.keys(pgPositions).length === 0
                ? 'Flat'
                : Object.entries(pgPositions)
                    .map(([t, n]) => `${t} ${n > 0 ? '+' : ''}${n}`)
                    .join(', ')}
            </Text>
          </View>
          <Text style={styles.fieldHint}>
            Reversals (e.g. BUY signal while short) project to ±limit and pass.
            Closes never blocked. Set per-instrument overrides via the API if
            different limits are needed per ticker (default applies to all).
          </Text>
        </Section>

        {/* Restart-Safety Gate */}
        <Section title="8. Restart-Safety Gate">
          <View style={styles.row}>
            <Text style={styles.fieldLabel}>Status</Text>
            <Text style={[
              styles.fieldValue,
              { fontWeight: '600',
                color: rgState.status === 'ok' && !rgLocked ? Colors.green
                  : rgState.status === 'timed_out' ? Colors.red
                  : Colors.amber },
            ]}>
              {rgState.status === 'timed_out' ? 'TIMED OUT'
                : rgState.status === 'reconciling' ? 'Reconciling…'
                : rgLocked ? 'Heartbeat stale' : 'OK'}
            </Text>
          </View>
          {rgState.duration_seconds != null ? (
            <View style={styles.row}>
              <Text style={styles.fieldLabel}>Last reconcile took</Text>
              <Text style={styles.fieldValue}>{rgState.duration_seconds.toFixed(1)}s</Text>
            </View>
          ) : null}
          {rgState.reason ? (
            <Text style={[styles.fieldHint, { color: rgState.status === 'timed_out' ? Colors.red : Colors.dark }]}>
              {rgState.reason}
            </Text>
          ) : null}
          {rgState.status === 'timed_out' ? (
            <TouchableOpacity
              style={[styles.ibAuthButton, { backgroundColor: Colors.red, marginTop: 12 },
                      rgResetting && { opacity: 0.5 }]}
              onPress={() =>
                Alert.alert(
                  'Reset reconcile gate?',
                  'New trades will resume immediately. Only do this if you have verified broker positions match the bot state.',
                  [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Reset', style: 'destructive', onPress: resetReconcileGate },
                  ],
                )
              }
              disabled={rgResetting}
            >
              <Text style={styles.ibAuthText}>
                {rgResetting ? 'Resetting…' : 'Reset gate'}
              </Text>
            </TouchableOpacity>
          ) : null}
          <Text style={styles.fieldHint}>
            On bot restart, webhooks return 503 until the first reconcile pass
            completes (typically 2–10 s). Hard timeout: 2 min. Defense against
            acting on stale strat_pos / diary state before the bot has
            re-synced with the broker.
          </Text>
        </Section>

        {/* Emergency Flatten All */}
        <Section title="9. Emergency">
          <Text style={styles.fieldHint}>
            Queues a MKT close for every currently-open futures position.
            Use when the bot is misbehaving and you need to be flat now.
            Closes always pass through bot gates; reconciler still runs.
          </Text>
          <TouchableOpacity
            style={[styles.ibAuthButton, { backgroundColor: Colors.red, marginTop: 12 },
                    flattening && { opacity: 0.5 }]}
            onPress={() =>
              Alert.alert(
                'Flatten ALL open positions?',
                'This queues a MKT close for every open futures contract at IB. '
                + 'Bracket SLs / TPs will be cancelled. You will be FLAT in seconds.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Flatten All', style: 'destructive', onPress: flattenAll },
                ],
              )
            }
            disabled={flattening}
          >
            <Text style={styles.ibAuthText}>
              {flattening ? 'Queuing…' : '⚠️  Flatten All Positions'}
            </Text>
          </TouchableOpacity>
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
