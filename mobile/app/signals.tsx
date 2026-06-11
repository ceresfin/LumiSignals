import { useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  RefreshControl, SafeAreaView,
} from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';

type SignalEvent = {
  event_time: string;
  state: string;
  ticker: string;
  strategy_id: string;
  reason: string | null;
  direction: 'BUY' | 'SELL' | 'CLOSE_LONG' | 'CLOSE_SHORT' | null;
  entry_price: number | null;
  exit_price: number | null;
  stop_price: number | null;
  realized_pl: number | null;
  broker_trade_id: string | null;
  entry_time?: string | null;   // server enriches CLOSED rows with the matching OPEN's time
};

type Range = 'today' | 'wtd' | 'mtd' | 'all';
type StateFilter = 'all' | 'entries' | 'closed' | 'missed';

type MissedSignal = {
  bar_time: string;
  direction: 'BUY' | 'SELL';
  reason: string;
  close: number;
  vwap: number;
};

// Build start/end of the selected window. "Today" anchors at the most-recent
// 9:30 AM ET — matches the trading-day boundary the dashboard already uses.
function rangeWindow(range: Range): { since: string | null; until: string | null } {
  if (range === 'all') return { since: null, until: null };
  const now = new Date();
  const tzShort = now.toLocaleString('en-US', {
    timeZone: 'America/New_York', timeZoneName: 'short',
  });
  const offsetHours = tzShort.includes('EDT') ? 4 : 5;
  if (range === 'today') {
    const dayStart = new Date(now);
    dayStart.setUTCHours(9 + offsetHours, 30, 0, 0);
    if (now < dayStart) dayStart.setUTCDate(dayStart.getUTCDate() - 1);
    const overnightStart = new Date(now);
    overnightStart.setUTCHours(16 + offsetHours, 0, 0, 0);
    if (now < overnightStart) overnightStart.setUTCDate(overnightStart.getUTCDate() - 1);
    const earlier = dayStart < overnightStart ? dayStart : overnightStart;
    return { since: earlier.toISOString(), until: null };
  }
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (range === 'wtd') {
    const day = start.getDay();
    const daysBack = day === 0 ? 6 : day - 1;
    start.setDate(start.getDate() - daysBack);
  } else if (range === 'mtd') {
    start.setDate(1);
  }
  return { since: start.toISOString(), until: null };
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      timeZone: 'America/New_York',
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', second: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

// Short HH:MM AM/PM for the entry stamp on CLOSED rows.
function fmtTimeShort(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric', minute: '2-digit', hour12: true,
    });
  } catch {
    return iso;
  }
}

// Duration in compact form: "23s", "4m", "1h 12m".
function fmtDuration(fromIso: string, toIso: string): string {
  try {
    const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
    if (!Number.isFinite(ms) || ms < 0) return '';
    const secs = Math.round(ms / 1000);
    if (secs < 90) return `${secs}s`;
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  } catch {
    return '';
  }
}

function statePillStyle(state: string, direction: SignalEvent['direction']) {
  if (state === 'INTENT_OPEN' || state === 'OPEN') {
    return { bg: direction === 'BUY' ? '#e8f5e9' : '#fdecea',
             fg: direction === 'BUY' ? Colors.green : Colors.red };
  }
  if (state === 'INTENT_CLOSE' || state === 'CLOSED') {
    return { bg: '#eceff1', fg: Colors.dark };
  }
  if (state === 'STOP_FIRED') {
    // A stop-out is a closing event too — flag it red so it reads as a loss.
    return { bg: '#fdecea', fg: Colors.red };
  }
  if (state === 'MISSED') {
    return { bg: '#fff3e0', fg: Colors.amber };
  }
  if (state.startsWith('RECONCILE')) {
    return { bg: '#fff3e0', fg: Colors.amber };
  }
  return { bg: '#f5f5f5', fg: Colors.textMedium };
}

function dirArrow(d: SignalEvent['direction']): string {
  if (d === 'BUY') return '▲';
  if (d === 'SELL') return '▼';
  if (d === 'CLOSE_LONG') return '◀';
  if (d === 'CLOSE_SHORT') return '◀';
  return '·';
}

export default function SignalsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ strategy?: string; ticker?: string;
                                        strategyName?: string }>();
  const strategy = params.strategy || 'futures_2n20';
  const ticker = params.ticker || '';
  const strategyName = params.strategyName || strategy;

  const [events, setEvents] = useState<SignalEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>('today');
  const [stateFilter, setStateFilter] = useState<StateFilter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [missed, setMissed] = useState<MissedSignal[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const { since, until } = rangeWindow(range);
      const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';

      // Always fetch the diary events.
      const qs = new URLSearchParams({ strategy, limit: '1000' });
      if (ticker) qs.set('ticker', ticker);
      if (since) qs.set('since', since);
      if (until) qs.set('until', until);
      const resp = await fetch(`${API_BASE}/api/strategies/signals?${qs.toString()}`, {
        headers: { 'X-Sync-Key': syncKey },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const arr: SignalEvent[] = Array.isArray(data?.events) ? data.events.slice().reverse() : [];
      setEvents(arr);

      // Also fetch missed signals — replay 2n20 logic on cached bars and
      // diff against actual INTENT_OPENs. Only meaningful for 2n20+MES today.
      if (ticker && strategy.includes('2n20')) {
        const mqs = new URLSearchParams({ ticker, mode: 'missed' });
        if (since) mqs.set('since', since);
        if (until) mqs.set('until', until);
        try {
          const mresp = await fetch(
            `${API_BASE}/api/strategies/expected-signals?${mqs.toString()}`,
            { headers: { 'X-Sync-Key': syncKey } },
          );
          if (mresp.ok) {
            const mdata = await mresp.json();
            setMissed(Array.isArray(mdata?.missed) ? mdata.missed.slice().reverse() : []);
          } else {
            setMissed([]);
          }
        } catch {
          setMissed([]);
        }
      } else {
        setMissed([]);
      }
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, [range, strategy, ticker]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of events) c[e.state] = (c[e.state] || 0) + 1;
    return c;
  }, [events]);

  const visibleEvents = useMemo<SignalEvent[]>(() => {
    if (stateFilter === 'missed') {
      // Project missed signals onto the SignalEvent shape so the row
      // renderer can stay one code path.
      return missed.map(m => ({
        event_time: m.bar_time,
        state: 'MISSED',
        ticker: ticker || 'MES',
        strategy_id: strategy,
        reason: m.reason,
        direction: m.direction,
        entry_price: m.close,
        exit_price: null,
        stop_price: null,
        realized_pl: null,
        broker_trade_id: null,
      }));
    }
    if (stateFilter === 'all') return events;
    if (stateFilter === 'entries') {
      return events.filter(e => e.state === 'INTENT_OPEN' || e.state === 'OPEN');
    }
    // "Closed" = every exit, signal-based (CLOSED) AND stop-outs (STOP_FIRED).
    // Stops are real closed trades; excluding them made the counts look
    // unbalanced (15 entries / 3 closed hid 12 stop-outs).
    return events.filter(e => e.state === 'CLOSED' || e.state === 'STOP_FIRED');
  }, [events, missed, stateFilter, ticker, strategy]);

  const totalPl = useMemo(() => {
    if (stateFilter !== 'closed') return null;
    return visibleEvents.reduce((acc, e) => acc + (e.realized_pl || 0), 0);
  }, [visibleEvents, stateFilter]);

  const onRefresh = () => { setRefreshing(true); load(); };

  return (
    <SafeAreaView style={styles.container}>
      <Stack.Screen options={{ title: 'Signals', headerBackTitle: 'Back' }} />
      <View style={styles.header}>
        <Text style={styles.title}>{strategyName}</Text>
        <Text style={styles.subtitle}>
          {ticker ? `${ticker} · ` : ''}
          {stateFilter === 'missed'
            ? `${missed.length} missed (expected but no webhook arrived)`
            : stateFilter === 'closed'
              ? `${counts.CLOSED || 0} closed · ${counts.STOP_FIRED || 0} stopped${totalPl != null ? `  ·  ${totalPl >= 0 ? '+' : ''}$${totalPl.toFixed(2)}` : ''}`
              : stateFilter === 'entries'
                ? `${visibleEvents.length} entry signals`
                : `${events.length} events`
                  + (counts.INTENT_OPEN ? `  ·  ${counts.INTENT_OPEN} entries` : '')
                  + (counts.CLOSED ? `  ·  ${counts.CLOSED} closed` : '')
                  + (counts.STOP_FIRED ? `  ·  ${counts.STOP_FIRED} stopped` : '')
                  + (missed.length ? `  ·  ${missed.length} missed` : '')}
        </Text>
      </View>

      <View style={styles.pillBar}>
        {(['today', 'wtd', 'mtd', 'all'] as const).map(k => (
          <TouchableOpacity
            key={k}
            style={[styles.pill, range === k && styles.pillActive]}
            onPress={() => setRange(k)}
          >
            <Text style={[styles.pillText, range === k && styles.pillTextActive]}>
              {k === 'today' ? 'Today' : k === 'wtd' ? 'WTD' : k === 'mtd' ? 'MTD' : 'All'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.pillBar}>
        {([
          ['all', 'All'],
          ['entries', 'Entries'],
          ['closed', 'Closed'],
          ['missed', `Missed${missed.length ? ` (${missed.length})` : ''}`],
        ] as const).map(([k, label]) => (
          <TouchableOpacity
            key={k}
            style={[styles.pill, stateFilter === k && styles.pillActive]}
            onPress={() => setStateFilter(k)}
          >
            <Text style={[styles.pillText, stateFilter === k && styles.pillTextActive]}>
              {label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>Failed to load: {error}</Text>
          <TouchableOpacity onPress={load} style={styles.retryBtn}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : loading && events.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={Colors.olive} />
        </View>
      ) : (
        <FlatList
          data={visibleEvents}
          keyExtractor={(e, i) => `${e.event_time}-${e.state}-${i}`}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          ItemSeparatorComponent={() => <View style={styles.sep} />}
          renderItem={({ item }) => {
            const pill = statePillStyle(item.state, item.direction);
            const isClosed = item.state === 'CLOSED' || item.state === 'STOP_FIRED';
            return (
              <View style={styles.row}>
                <View style={styles.rowTopLine}>
                  <View style={[styles.statePill, { backgroundColor: pill.bg }]}>
                    <Text style={[styles.stateText, { color: pill.fg }]}>
                      {dirArrow(item.direction)} {item.state}
                    </Text>
                  </View>
                  <Text style={styles.tickerText}>{item.ticker}</Text>
                  <View style={styles.timeBlock}>
                    <Text style={styles.timeText}>{fmtTime(item.event_time)}</Text>
                    {isClosed && item.entry_time ? (
                      <Text style={styles.entryTimeText}>
                        opened {fmtTimeShort(item.entry_time)} ({fmtDuration(item.entry_time, item.event_time)})
                      </Text>
                    ) : null}
                  </View>
                </View>
                {(item.entry_price != null || item.exit_price != null
                  || item.stop_price != null || item.realized_pl != null) && (
                  <View style={styles.rowPrices}>
                    {item.entry_price != null && (
                      <Text style={styles.priceCell}>entry {item.entry_price}</Text>
                    )}
                    {item.exit_price != null && (
                      <Text style={styles.priceCell}>exit {item.exit_price}</Text>
                    )}
                    {item.stop_price != null && (
                      <Text style={styles.priceCell}>stop {item.stop_price}</Text>
                    )}
                    {item.realized_pl != null && (
                      <Text style={[styles.priceCell, {
                        color: item.realized_pl >= 0 ? Colors.green : Colors.red,
                        fontWeight: '600',
                      }]}>
                        {item.realized_pl >= 0 ? '+' : ''}${item.realized_pl}
                      </Text>
                    )}
                  </View>
                )}
                {item.reason && (
                  <Text style={styles.reasonText} numberOfLines={2}>{item.reason}</Text>
                )}
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.emptyText}>
                {stateFilter === 'missed'
                  ? 'No missed signals in this range — every Pine signal we expected was also received.'
                  : events.length === 0
                    ? 'No signals in this range'
                    : `No ${stateFilter === 'closed' ? 'closed trades' : 'entries'} in this range`}
              </Text>
            </View>
          }
          contentContainerStyle={visibleEvents.length === 0 ? { flex: 1 } : undefined}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 4 },
  title: { fontSize: 18, fontWeight: '700', color: Colors.dark },
  subtitle: { fontSize: 12, color: Colors.textMedium, marginTop: 2 },
  pillBar: {
    flexDirection: 'row', paddingHorizontal: 12, paddingVertical: 8,
    gap: 6,
  },
  pill: {
    paddingHorizontal: 14, paddingVertical: 6, borderRadius: 16,
    backgroundColor: Colors.white, borderWidth: 1, borderColor: '#e0ddd6',
  },
  pillActive: { backgroundColor: Colors.olive, borderColor: Colors.olive },
  pillText: { fontSize: 12, color: Colors.textMedium },
  pillTextActive: { color: Colors.white, fontWeight: '600' },
  row: { paddingHorizontal: 16, paddingVertical: 10, backgroundColor: Colors.white },
  rowTopLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statePill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4 },
  stateText: { fontSize: 11, fontWeight: '600' },
  tickerText: { fontSize: 12, color: Colors.dark, fontWeight: '600' },
  timeBlock: { marginLeft: 'auto', alignItems: 'flex-end' },
  timeText: { fontSize: 11, color: Colors.textLight },
  entryTimeText: { fontSize: 10, color: Colors.textLight, marginTop: 1, fontStyle: 'italic' },
  rowPrices: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 6 },
  priceCell: { fontSize: 11, color: Colors.textMedium, fontVariant: ['tabular-nums'] },
  reasonText: { fontSize: 11, color: Colors.textLight, marginTop: 4, fontStyle: 'italic' },
  sep: { height: 1, backgroundColor: '#ece9e3' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 },
  errorText: { color: Colors.red, fontSize: 13, marginBottom: 12, textAlign: 'center' },
  emptyText: { color: Colors.textLight, fontSize: 13 },
  retryBtn: { backgroundColor: Colors.olive, paddingHorizontal: 16, paddingVertical: 8, borderRadius: 6 },
  retryText: { color: Colors.white, fontSize: 13, fontWeight: '600' },
});
