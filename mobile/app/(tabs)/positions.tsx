import { useEffect, useState } from 'react';
import { Alert, View, Text, FlatList, StyleSheet, RefreshControl, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';
import { strategyBadgeText } from '@/lib/strategyLabel';

type Position = {
  id: number;
  broker: string;
  broker_trade_id: string;
  instrument: string;
  asset_type: string;
  direction: string;
  units: number;
  contracts: number;
  entry_price: number;
  stop_loss: number;
  unrealized_pl: number;
  pips: number;
  strategy: string;
  model: string;
  spread_type: string;
  sell_strike: number;
  buy_strike: number;
  right: string;
  expiration: string;
  take_profit: number | null;
  opened_at: string;
  updated_at: string;
};

const STRATEGY_TIMEFRAMES: Record<string, string> = {
  'scalp_2n20': '2m',
  'vwap_2n20': '2m',
  '2n20': '2m',
  'scalp': '15m',
  'intraday': '1h',
  'swing': '1d',
  'orb_breakout': '15m',
};

function getChartTimeframe(model?: string, strategy?: string): string {
  if (model && STRATEGY_TIMEFRAMES[model]) return STRATEGY_TIMEFRAMES[model];
  if (strategy && STRATEGY_TIMEFRAMES[strategy]) return STRATEGY_TIMEFRAMES[strategy];
  return '15m';
}

// Approximate USD value of a price move on a position. Handles the three
// pair shapes correctly; falls back to the quote-currency-divided-by-entry
// approximation for crosses (matches trade_tracker.py's logic).
function priceToUsd(instrument: string, units: number, entry: number, distance: number): number {
  if (!units || !distance) return 0;
  const dist = Math.abs(distance);
  // X_USD pairs (EUR_USD, GBP_USD, AUD_USD, NZD_USD): pip value is in USD.
  if (instrument.endsWith('_USD')) return units * dist;
  // USD_X pairs (USD_JPY, USD_CAD, USD_CHF): pip in quote currency,
  // approximate USD via entry price.
  if (instrument.startsWith('USD_')) return entry ? units * dist / entry : 0;
  // Cross pairs (EUR_GBP, AUD_NZD, ...): rough approximation.
  return entry ? units * dist / entry : 0;
}

// Risk / reward for a position in dollars. Reward returns 0 if no take_profit
// is set. Futures use multiplier × contracts; forex uses the pip math above.
function positionRiskReward(p: Position): { risk: number; reward: number } {
  const entry = p.entry_price || 0;
  const stop = p.stop_loss || 0;
  const tp = p.take_profit || 0;
  if (p.asset_type === 'futures') {
    // MES is $5/pt, ES is $50/pt, NQ is $20/pt.
    const mult = p.instrument === 'ES' ? 50 : p.instrument === 'NQ' ? 20 : 5;
    const contracts = p.contracts || 1;
    return {
      risk: stop ? Math.abs(entry - stop) * mult * contracts : 0,
      reward: tp ? Math.abs(tp - entry) * mult * contracts : 0,
    };
  }
  if (p.asset_type === 'forex') {
    const units = p.units || 0;
    return {
      risk: stop ? priceToUsd(p.instrument, units, entry, entry - stop) : 0,
      reward: tp ? priceToUsd(p.instrument, units, entry, tp - entry) : 0,
    };
  }
  return { risk: 0, reward: 0 };
}

function PositionRow({ position, onChartPress, onClose }: {
  position: Position;
  onChartPress: (instrument: string, tf: string) => void;
  onClose: (p: Position) => void;
}) {
  const dir = position.direction === 'LONG' || position.direction === 'BUY' ? 'BUY' : 'SELL';
  const pl = position.unrealized_pl || 0;
  const isOptions = position.asset_type === 'options';
  const { risk, reward } = positionRiskReward(position);
  const rr = risk > 0 && reward > 0 ? (reward / risk).toFixed(1) : '';

  return (
    <View style={styles.posRow}>
      <View style={styles.posTop}>
        <TouchableOpacity onPress={() => onChartPress(position.instrument, getChartTimeframe(position.model, position.strategy))}>
          <Text style={[styles.posInstrument, { textDecorationLine: 'underline' }]}>{position.instrument}</Text>
        </TouchableOpacity>
        <View style={[styles.dirBadge, { backgroundColor: dir === 'BUY' ? '#e8f5e9' : '#fdecea' }]}>
          <Text style={[styles.dirText, { color: dir === 'BUY' ? Colors.green : Colors.red }]}>{dir}</Text>
        </View>
        {position.contracts > 1 ? (
          <Text style={styles.qtyText}>×{position.contracts}</Text>
        ) : null}
        <View style={[styles.brokerBadge, {
          backgroundColor: position.broker === 'oanda' ? '#e3f2fd' : '#f3e5f5',
        }]}>
          <Text style={[styles.brokerText, {
            color: position.broker === 'oanda' ? '#1565c0' : '#7b1fa2',
          }]}>
            {position.broker === 'oanda' ? 'FX' : 'IB'}
          </Text>
        </View>
        <View style={{ flex: 1 }} />
        <Text style={[styles.posPl, { color: pl >= 0 ? Colors.green : Colors.red }]}>
          {pl >= 0 ? '+' : ''}${pl.toFixed(2)}
        </Text>
      </View>

      <View style={styles.posDetails}>
        <View style={styles.posDetail}>
          <Text style={styles.posDetailLabel}>Entry</Text>
          <Text style={styles.posDetailValue}>
            {position.entry_price ? position.entry_price.toFixed(position.instrument.includes('JPY') ? 3 : 5) : '--'}
          </Text>
        </View>
        {position.stop_loss ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Stop</Text>
            <Text style={[styles.posDetailValue, { color: Colors.red }]}>
              {position.stop_loss.toFixed(position.instrument.includes('JPY') ? 3 : 5)}
            </Text>
          </View>
        ) : null}
        {position.pips ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Pips</Text>
            <Text style={[styles.posDetailValue, { color: position.pips >= 0 ? Colors.green : Colors.red }]}>
              {position.pips.toFixed(1)}
            </Text>
          </View>
        ) : null}
        {position.opened_at ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Duration</Text>
            <Text style={styles.posDetailValue}>
              {(() => {
                const mins = Math.round((Date.now() - new Date(position.opened_at).getTime()) / 60000);
                if (mins < 60) return mins + 'm';
                if (mins < 1440) return Math.floor(mins / 60) + 'h ' + (mins % 60) + 'm';
                return Math.floor(mins / 1440) + 'd ' + Math.floor((mins % 1440) / 60) + 'h';
              })()}
            </Text>
          </View>
        ) : null}
        {isOptions && position.spread_type ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Spread</Text>
            <Text style={styles.posDetailValue}>{position.spread_type}</Text>
          </View>
        ) : null}
        {isOptions && position.sell_strike ? (
          <View style={styles.posDetail}>
            <Text style={styles.posDetailLabel}>Strikes</Text>
            <Text style={styles.posDetailValue}>
              {position.sell_strike}/{position.buy_strike}
            </Text>
          </View>
        ) : null}
      </View>

      {(risk > 0 || reward > 0) ? (
        <View style={styles.rrRow}>
          {risk > 0 ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>RISK</Text>
              <Text style={[styles.rrValue, { color: Colors.red }]}>
                ${risk.toFixed(2)}
              </Text>
            </View>
          ) : null}
          {reward > 0 ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>REWARD</Text>
              <Text style={[styles.rrValue, { color: Colors.green }]}>
                ${reward.toFixed(2)}
              </Text>
            </View>
          ) : null}
          {rr ? (
            <View style={styles.rrItem}>
              <Text style={styles.rrLabel}>R:R</Text>
              <Text style={styles.rrValue}>{rr}</Text>
            </View>
          ) : null}
        </View>
      ) : null}

      <View style={styles.posFooter}>
        <Text style={styles.posTime}>
          {position.opened_at ? new Date(position.opened_at).toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
          }) : ''}
        </Text>
        <Text style={[styles.modelBadge, {
          color: position.model?.includes('2n20') ? Colors.amber : Colors.scalp,
        }]}>
          {strategyBadgeText(position.strategy, position.model)}
        </Text>
        <TouchableOpacity
          style={styles.closeBtn}
          onPress={() => onClose(position)}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Text style={styles.closeBtnText}>Close</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function Positions() {
  const { user } = useAuth();
  const router = useRouter();
  const [allPositions, setAllPositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState('forex');
  const [refreshing, setRefreshing] = useState(false);
  const [zones, setZones] = useState<any[]>([]);

  const TABS = [
    { key: 'forex', label: 'Forex', filter: (p: Position) => p.broker === 'oanda' || p.asset_type === 'forex' },
    { key: 'stocks', label: 'Stocks', filter: (p: Position) => p.asset_type === 'stock' && !p.instrument?.startsWith('I:') },
    { key: 'options', label: 'Options', filter: (p: Position) => p.asset_type === 'options' },
    { key: 'indices', label: 'Indices', filter: (p: Position) => !!p.instrument?.startsWith('I:') },
    { key: 'futures', label: 'Futures', filter: (p: Position) => p.asset_type === 'futures' && !p.instrument?.startsWith('I:') },
  ];

  const loadPositions = async () => {
    if (!user) return;
    try {
      const { data } = await supabase
        .from('positions')
        .select('*')
        .eq('user_id', user.id)
        .order('opened_at', { ascending: false });

      if (data) setAllPositions(data);
    } catch (e) {
      console.error('Positions load error:', e);
    }
  };

  const loadZones = async () => {
    try {
      const resp = await fetch('https://bot.lumitrade.ai/api/watchlist/zones');
      const data = await resp.json();
      setZones(data.zones || []);
    } catch { }
  };

  useEffect(() => { loadPositions(); loadZones(); }, [user]);
  useEffect(() => {
    const interval = setInterval(loadZones, 30000);
    return () => clearInterval(interval);
  }, []);

  // Realtime: live position updates
  useEffect(() => {
    if (!user) return;
    const channel = supabase
      .channel('positions-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'positions', filter: `user_id=eq.${user.id}` },
        () => { loadPositions(); }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [user]);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadPositions(), loadZones()]);
    setRefreshing(false);
  };

  const tab = TABS.find(t => t.key === activeTab)!;
  const positions = allPositions.filter(tab.filter);
  const totalPl = positions.reduce((s, p) => s + (p.unrealized_pl || 0), 0);

  // Total exposure summary in the header. Futures/options trade in contracts;
  // forex in units (often 25k+). We surface whichever is relevant so when the
  // bot accumulates (e.g. several BUYs not yet closed) the header makes the
  // real exposure obvious instead of just saying "1 position".
  const totalContracts = positions.reduce((s, p) => s + (p.contracts || 0), 0);
  const totalUnits = positions.reduce((s, p) => s + (p.units || 0), 0);
  const exposureLabel = (() => {
    if (activeTab === 'forex') {
      if (totalUnits >= 1000) return `${Math.round(totalUnits / 1000)}k units`;
      if (totalUnits > 0) return `${totalUnits} units`;
      return '';
    }
    if (activeTab === 'options') {
      return totalContracts > 0 ? `${totalContracts} spread${totalContracts !== 1 ? 's' : ''}` : '';
    }
    // Futures / Stocks / Indices
    return totalContracts > 0 ? `${totalContracts} contract${totalContracts !== 1 ? 's' : ''}` : '';
  })();

  // Manual close button — confirms via native Alert, posts to the server's
  // /api/positions/close endpoint, which routes per broker/asset_type.
  const handleClose = (p: Position) => {
    const pl = p.unrealized_pl || 0;
    const plStr = (pl >= 0 ? '+' : '') + '$' + pl.toFixed(2);
    const dir = p.direction === 'LONG' || p.direction === 'BUY' ? 'BUY' : 'SELL';
    Alert.alert(
      'Close trade?',
      `${p.instrument} ${dir} — unrealized ${plStr}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Close',
          style: 'destructive',
          onPress: async () => {
            try {
              const syncKey = process.env.EXPO_PUBLIC_LUMI_SYNC_KEY || '';
              const resp = await fetch('https://bot.lumitrade.ai/api/positions/close', {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'X-Sync-Key': syncKey,
                },
                body: JSON.stringify({
                  broker: p.broker,
                  asset_type: p.asset_type,
                  instrument: p.instrument,
                  broker_trade_id: p.broker_trade_id,
                  direction: p.direction,
                  strategy: p.strategy,
                  contracts: p.contracts || 1,
                  // Options-only fields (no-op for forex/futures)
                  spread_type: p.spread_type,
                  right: p.right,
                  expiration: p.expiration,
                  sell_strike: p.sell_strike,
                  buy_strike: p.buy_strike,
                }),
              });
              const result = await resp.json();
              if (!resp.ok) {
                Alert.alert('Close failed', result.error || `HTTP ${resp.status}`);
                return;
              }
              // Optimistic UI: remove the row immediately (sync will confirm in ~10s)
              setAllPositions(prev => prev.filter(row => row.id !== p.id));
              // Backstop refresh in case the server already wrote a state update.
              setTimeout(() => loadPositions(), 1500);
            } catch (e: any) {
              Alert.alert('Close failed', e?.message || String(e));
            }
          },
        },
      ],
    );
  };

  // Filter zones by active tab
  const isForexZone = (z: any) => z.instrument?.includes('_');
  const isIndexZone = (z: any) => z.instrument?.startsWith('I:');
  const isFuturesZone = (z: any) => ['MES', 'ES', 'NQ', 'GOLD', 'OIL'].includes(z.instrument);
  const isStockZone = (z: any) => !isForexZone(z) && !isIndexZone(z) && !isFuturesZone(z);

  const filteredZones = zones.filter(z => {
    if (activeTab === 'forex') return isForexZone(z);
    if (activeTab === 'stocks') return isStockZone(z);
    if (activeTab === 'options') return false;
    if (activeTab === 'indices') return isIndexZone(z);
    if (activeTab === 'futures') return isFuturesZone(z);
    return true;
  });

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Open Positions</Text>
          <Text style={styles.headerSubtitle}>
            {positions.length} position{positions.length !== 1 ? 's' : ''}
            {exposureLabel ? ` · ${exposureLabel}` : ''}
          </Text>
        </View>
        <View style={styles.plSummary}>
          <Text style={styles.plLabel}>Unrealized</Text>
          <Text style={[styles.plTotal, { color: totalPl >= 0 ? Colors.green : Colors.red }]}>
            {totalPl >= 0 ? '+' : ''}${totalPl.toFixed(2)}
          </Text>
        </View>
      </View>

      {/* Broker Tabs */}
      <View style={styles.tabBar}>
        {TABS.map(t => (
          <TouchableOpacity
            key={t.key}
            style={[styles.tab, activeTab === t.key && styles.tabActive]}
            onPress={() => setActiveTab(t.key)}
          >
            <Text style={[styles.tabText, activeTab === t.key && styles.tabTextActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={positions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => <PositionRow position={item} onClose={handleClose} onChartPress={(sym, tf) => router.push({
          pathname: '/chart',
          params: {
            symbol: sym,
            interval: tf,
            entry: item.entry_price?.toString(),
            stop: item.stop_loss?.toString(),
            direction: item.direction,
            strategy: item.strategy || item.model || '',
          }
        })} />}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 20 }}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No open positions</Text>
            <Text style={styles.emptySubtext}>Positions appear here when the bot opens a trade</Text>
          </View>
        }
        ListFooterComponent={
          <View style={styles.watchlistSection}>
            <Text style={styles.watchlistTitle}>
              HTF Zones {filteredZones.length > 0 ? `(${filteredZones.filter(z => z.status === 'activated').length} activated)` : ''}
            </Text>
            {filteredZones.length === 0 ? (
              <Text style={{ color: Colors.textLight, fontSize: 13 }}>No zones being monitored</Text>
            ) : (
              filteredZones.map((z, i) => {
                const isActivated = z.status === 'activated';
                const isSupply = z.zone_type === 'supply';
                const tfColors: Record<string, string> = { '1mo': '#ff9800', '1w': '#ffeb3b', '1d': '#2196f3', '4h': '#ce93d8', '1h': '#66bb6a' };
                const tfLabels: Record<string, string> = { '1mo': 'M', '1w': 'W', '1d': 'D', '4h': '4H', '1h': '1H' };
                const tfColor = tfColors[z.zone_timeframe] || '#888';
                const trends = z.trends || {};

                return (
                  <TouchableOpacity
                    key={`${z.instrument}-${z.zone_type}-${z.zone_timeframe}-${i}`}
                    style={[styles.zoneCard, isActivated && styles.zoneCardActivated]}
                    onPress={() => router.push({
                      pathname: '/chart',
                      params: { symbol: z.instrument, interval: z.zone_timeframe, strategy: 'htf_levels' }
                    })}
                  >
                    <View style={styles.zoneTop}>
                      <Text style={styles.zoneTicker}>{z.instrument}</Text>
                      <View style={[styles.zoneBadge, { backgroundColor: isSupply ? '#fdecea' : '#e8f5e9' }]}>
                        <Text style={[styles.zoneBadgeText, { color: isSupply ? Colors.red : Colors.green }]}>
                          {isSupply ? 'SUPPLY' : 'DEMAND'}
                        </Text>
                      </View>
                      <View style={[styles.tfBadge, { backgroundColor: tfColor + '22', borderColor: tfColor }]}>
                        <Text style={[styles.tfBadgeText, { color: tfColor }]}>
                          {tfLabels[z.zone_timeframe] || z.zone_timeframe}
                        </Text>
                      </View>
                      {isActivated && (
                        <View style={styles.activatedDot} />
                      )}
                      <View style={{ flex: 1 }} />
                      <Text style={styles.zoneScore}>{z.bias_score}</Text>
                    </View>
                    <View style={styles.zoneBottom}>
                      <Text style={styles.zonePrice}>
                        @ {z.zone_price.toFixed(z.instrument.includes('JPY') ? 3 : (z.instrument.includes('_') ? 5 : 2))}
                      </Text>
                      <Text style={styles.zoneModel}>
                        {strategyBadgeText('htf_levels', z.model)}
                      </Text>
                      <View style={styles.trendRow}>
                        {Object.entries(trends).map(([tf, dir]) => (
                          <Text key={tf} style={[styles.trendBadge, {
                            color: dir === 'bullish' ? Colors.green : dir === 'bearish' ? Colors.red : Colors.textLight
                          }]}>
                            {tf[0]}{dir === 'bullish' ? '↑' : dir === 'bearish' ? '↓' : '→'}
                          </Text>
                        ))}
                      </View>
                    </View>
                  </TouchableOpacity>
                );
              })
            )}
          </View>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 12,
  },
  headerTitle: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  headerSubtitle: { fontSize: 12, color: Colors.textLight, marginTop: 2 },
  tabBar: {
    flexDirection: 'row',
    marginHorizontal: 16,
    marginBottom: 12,
    backgroundColor: Colors.white,
    borderRadius: 10,
    padding: 3,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 8,
  },
  tabActive: { backgroundColor: Colors.olive },
  tabText: { fontSize: 13, fontWeight: '500', color: Colors.textLight },
  tabTextActive: { color: Colors.gold },
  plSummary: { alignItems: 'flex-end' },
  plLabel: { fontSize: 10, color: Colors.textLight, letterSpacing: 0.5, textTransform: 'uppercase' },
  plTotal: { fontSize: 20, fontWeight: '300' },
  posRow: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  posTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
  },
  posInstrument: { fontSize: 16, fontWeight: '600', color: Colors.dark },
  dirBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  dirText: { fontSize: 11, fontWeight: '600' },
  brokerBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 50 },
  brokerText: { fontSize: 10, fontWeight: '600' },
  posPl: { fontSize: 18, fontWeight: '500' },
  posDetails: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
    marginBottom: 8,
  },
  posDetail: {},
  posDetailLabel: { fontSize: 10, color: Colors.textLight, textTransform: 'uppercase', letterSpacing: 0.3 },
  posDetailValue: { fontSize: 14, color: Colors.dark, marginTop: 1 },
  posFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#f5f3ee',
    paddingTop: 8,
  },
  posTime: { fontSize: 11, color: Colors.textLight },
  modelBadge: { fontSize: 10, fontWeight: '700', letterSpacing: 0.3 },
  rrRow: {
    flexDirection: 'row',
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#f0ebe2',
    gap: 18,
  },
  rrItem: { flexDirection: 'column' },
  rrLabel: {
    fontSize: 9,
    fontWeight: '600',
    color: Colors.textLight,
    letterSpacing: 0.6,
  },
  rrValue: {
    fontSize: 14,
    fontWeight: '500',
    color: Colors.dark,
    marginTop: 2,
  },
  qtyText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.dark,
    marginLeft: -4,
  },
  closeBtn: {
    marginLeft: 10,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: Colors.red,
  },
  closeBtnText: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.red,
    letterSpacing: 0.5,
  },
  watchlistSection: { marginTop: 24, paddingBottom: 20 },
  watchlistTitle: { fontSize: 16, fontWeight: '500', color: Colors.dark, marginBottom: 12 },
  zoneCard: {
    backgroundColor: Colors.white, borderRadius: 12, padding: 14,
    marginBottom: 8, borderLeftWidth: 3, borderLeftColor: '#e0ddd8',
  },
  zoneCardActivated: {
    borderLeftColor: Colors.green,
    backgroundColor: '#f8fdf8',
  },
  zoneTop: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  zoneTicker: { fontSize: 15, fontWeight: '600', color: Colors.dark },
  zoneBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  zoneBadgeText: { fontSize: 10, fontWeight: '700' },
  tfBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, borderWidth: 1 },
  tfBadgeText: { fontSize: 10, fontWeight: '700' },
  activatedDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.green },
  zoneScore: { fontSize: 14, fontWeight: '600', color: Colors.olive },
  zoneBottom: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  zonePrice: { fontSize: 13, color: Colors.textMedium },
  zoneModel: { fontSize: 10, fontWeight: '700', color: Colors.textLight, letterSpacing: 0.3 },
  trendRow: { flexDirection: 'row', gap: 4 },
  trendBadge: { fontSize: 11, fontWeight: '600' },
  empty: { alignItems: 'center', paddingTop: 60 },
  emptyText: { fontSize: 16, color: Colors.textLight },
  emptySubtext: { fontSize: 13, color: Colors.textLight, marginTop: 6, textAlign: 'center' },
});
