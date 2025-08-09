import React, { useEffect, useRef, useState } from 'react';
import { 
  createChart, 
  ColorType, 
  IChartApi, 
  ISeriesApi, 
  CandlestickData as TVCandlestickData,
  IPriceLine,
  ITimeScaleApi,
  Time
} from 'lightweight-charts';
import { TrendingUp, TrendingDown, AlertCircle, ArrowUp, ArrowDown } from 'lucide-react';
import { api } from '../../services/api';

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface ActiveTrade {
  trade_id: string;
  instrument: string;
  units: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  take_profit_price: number;
  stop_loss_price: number;
  pips_moved: number;
  strategy_name: string;
  direction: 'Long' | 'Short';
  open_time: string;
}

interface LightweightTradingViewChartWithTradesProps {
  currencyPair: string;
  timeframe?: string;
  height?: number;
  selectedStrategies?: string[];
}

// Color schemes for different strategies (brighter, more visible colors)
const STRATEGY_COLORS = [
  { entry: '#00BFFF', target: '#00FF7F', stop: '#FF4500' }, // Bright Blue, Bright Green, Bright Red
  { entry: '#1E90FF', target: '#32CD32', stop: '#DC143C' }, // Dodger Blue, Lime Green, Crimson
  { entry: '#4169E1', target: '#228B22', stop: '#B22222' }, // Royal Blue, Forest Green, Fire Brick
  { entry: '#00CED1', target: '#9ACD32', stop: '#FF6347' }, // Dark Turquoise, Yellow Green, Tomato
];

export const LightweightTradingViewChartWithTrades: React.FC<LightweightTradingViewChartWithTradesProps> = ({
  currencyPair,
  timeframe = 'H1',
  height = 300,
  selectedStrategies = []
}) => {
  console.log(`🚀 TradingViewChartWithTrades mounted for ${currencyPair}, strategies:`, selectedStrategies);
  
  // Determine if this is a JPY pair for proper decimal formatting
  const isJPYPair = currencyPair.includes('JPY');
  const decimalPlaces = isJPYPair ? 3 : 5; // JPY: 3 decimals (e.g. 150.123), Others: 5 decimals (e.g. 1.37402)
  
  console.log(`🔍 Y-axis precision debug for ${currencyPair}:`, {
    isJPYPair,
    priceFormatPrecision: isJPYPair ? 2 : 4,
    decimalPlaces,
    minMove: isJPYPair ? 0.01 : 0.0001
  });
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<any[]>([]);
  
  const [candlestickData, setCandlestickData] = useState<CandlestickData[]>([]);
  const [activeTrades, setActiveTrades] = useState<ActiveTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number | null>(null);

  // Clean up chart on unmount
  useEffect(() => {
    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
      }
    };
  }, []);

  // Initialize chart when container is ready
  useEffect(() => {
    if (!chartContainerRef.current || loading || error) return;

    // Create chart with dark theme matching PipStop
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: '#1E1E1E' },
        textColor: '#B3B3B3',
      },
      grid: {
        vertLines: {
          color: '#333333',
          style: 1,
          visible: true,
        },
        horzLines: {
          color: '#555555',
          style: 1,
          visible: true,
        },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#8FC9CF',
          width: 1,
          style: 2,
          labelBackgroundColor: '#2C2C2C',
        },
        horzLine: {
          color: '#8FC9CF',
          width: 1,
          style: 2,
          labelBackgroundColor: '#2C2C2C',
        },
      },
      rightPriceScale: {
        borderColor: '#555555',
        scaleMargins: {
          top: 0.2,
          bottom: 0.2,
        },
        visible: true,
        entireTextOnly: false,
        drawTicks: true,
        alignLabels: true,
        minimumWidth: 120,
        autoScale: true,
        invertScale: false,
        borderVisible: true,
      },
      timeScale: {
        borderColor: '#333333',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Create candlestick series with PipStop colors
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#C7D9C5',
      downColor: '#C26A6A',
      borderUpColor: '#C7D9C5',
      borderDownColor: '#C26A6A',
      wickUpColor: '#C7D9C5',
      wickDownColor: '#C26A6A',
      priceFormat: {
        type: 'price',
        precision: isJPYPair ? 2 : 4,
        minMove: isJPYPair ? 0.01 : 0.0001,
      },
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [height, loading, error]);

  // Clear previous price lines and markers
  const clearOverlays = () => {
    if (candlestickSeriesRef.current) {
      priceLinesRef.current.forEach(line => {
        candlestickSeriesRef.current!.removePriceLine(line);
      });
      priceLinesRef.current = [];
      
      // Clear markers
      candlestickSeriesRef.current.setMarkers([]);
      markersRef.current = [];
    }
  };

  // Add trade overlays
  const addTradeOverlays = () => {
    console.log(`🎨 Adding trade overlays for ${currencyPair}:`, {
      hasChart: !!candlestickSeriesRef.current,
      selectedStrategies,
      activeTrades: activeTrades.map(t => ({ 
        instrument: t.instrument, 
        strategy: t.strategy_name,
        entry: t.entry_price,
        target: t.take_profit_price,
        stop: t.stop_loss_price
      }))
    });
    
    if (!candlestickSeriesRef.current || !chartRef.current) return;
    
    clearOverlays();
    
    // Filter trades by selected strategies
    const filteredTrades = selectedStrategies.length > 0
      ? activeTrades.filter(trade => selectedStrategies.includes(trade.strategy_name))
      : activeTrades;
    
    console.log(`🎯 Filtered ${filteredTrades.length} trades for ${currencyPair} with strategies:`, selectedStrategies);

    // Group trades by strategy for coloring
    const tradesByStrategy: { [key: string]: ActiveTrade[] } = {};
    filteredTrades.forEach(trade => {
      if (!tradesByStrategy[trade.strategy_name]) {
        tradesByStrategy[trade.strategy_name] = [];
      }
      tradesByStrategy[trade.strategy_name].push(trade);
    });

    // Get unique strategies and assign colors
    const strategies = Object.keys(tradesByStrategy);
    
    strategies.forEach((strategy, strategyIndex) => {
      const colorScheme = STRATEGY_COLORS[strategyIndex % STRATEGY_COLORS.length];
      const trades = tradesByStrategy[strategy];
      
      trades.forEach((trade, tradeIndex) => {
        console.log(`📍 Creating price lines for ${trade.instrument} - ${trade.strategy_name}:`, {
          entry: trade.entry_price,
          target: trade.take_profit_price,
          stop: trade.stop_loss_price,
          current: trade.current_price,
          colorScheme,
          // Check if prices are valid numbers
          entryValid: !isNaN(trade.entry_price) && trade.entry_price > 0,
          targetValid: !isNaN(trade.take_profit_price) && trade.take_profit_price > 0,
          stopValid: !isNaN(trade.stop_loss_price) && trade.stop_loss_price > 0
        });
        console.log('🎨 DEBUG: Color scheme being used:', colorScheme);
        console.log('🎨 DEBUG: Strategy Colors array:', STRATEGY_COLORS);
        
        // Validate price data before creating lines
        console.log('🔍 Validating prices:', {
          entry: trade.entry_price,
          entryType: typeof trade.entry_price,
          entryValid: trade.entry_price && !isNaN(trade.entry_price) && trade.entry_price > 0,
          target: trade.take_profit_price,
          targetType: typeof trade.take_profit_price,
          targetValid: trade.take_profit_price && !isNaN(trade.take_profit_price) && trade.take_profit_price > 0,
          stop: trade.stop_loss_price,
          stopType: typeof trade.stop_loss_price,
          stopValid: trade.stop_loss_price && !isNaN(trade.stop_loss_price) && trade.stop_loss_price > 0
        });
        
        // TEMPORARILY DISABLE VALIDATION TO FIX STRATEGY DROPDOWN
        /*
        if (!trade.entry_price || isNaN(trade.entry_price) || trade.entry_price <= 0) {
          console.error(`❌ Invalid entry price for ${trade.instrument}: ${trade.entry_price}`);
          return;
        }
        if (!trade.take_profit_price || isNaN(trade.take_profit_price) || trade.take_profit_price <= 0) {
          console.error(`❌ Invalid target price for ${trade.instrument}: ${trade.take_profit_price}`);
          return;
        }
        if (!trade.stop_loss_price || isNaN(trade.stop_loss_price) || trade.stop_loss_price <= 0) {
          console.error(`❌ Invalid stop price for ${trade.instrument}: ${trade.stop_loss_price}`);
          return;
        }
        */
        
        // Skip invalid prices but don't return early (allow strategy dropdown to work)
        if (!trade.entry_price || isNaN(trade.entry_price) || trade.entry_price <= 0) {
          console.warn(`⚠️ Skipping entry line for ${trade.instrument}: invalid price ${trade.entry_price}`);
        }
        if (!trade.take_profit_price || isNaN(trade.take_profit_price) || trade.take_profit_price <= 0) {
          console.warn(`⚠️ Skipping target line for ${trade.instrument}: invalid price ${trade.take_profit_price}`);
        }
        if (!trade.stop_loss_price || isNaN(trade.stop_loss_price) || trade.stop_loss_price <= 0) {
          console.warn(`⚠️ Skipping stop line for ${trade.instrument}: invalid price ${trade.stop_loss_price}`);
        }
        
        console.log('✅ Attempting to create lines...');
        
        // Add entry price line with custom label (if valid)
        if (trade.entry_price && !isNaN(trade.entry_price) && trade.entry_price > 0) {
          const entryLine = candlestickSeriesRef.current!.createPriceLine({
            price: trade.entry_price,
            color: colorScheme.entry,
            lineWidth: 4,
            lineStyle: 0, // Solid
            axisLabelVisible: true,
            title: `Entry ${trade.entry_price.toFixed(decimalPlaces)}`,
            lineVisible: true,
          });
          priceLinesRef.current.push(entryLine);
          console.log(`🔥 CACHE-BUST ${Date.now()}: Created BRIGHT ENTRY line at ${trade.entry_price.toFixed(5)} for ${trade.instrument} (color: ${colorScheme.entry})`);
        }

        // Add target price line with custom label - SUPER BRIGHT GREEN (if valid)
        if (trade.take_profit_price && !isNaN(trade.take_profit_price) && trade.take_profit_price > 0) {
          const targetLine = candlestickSeriesRef.current!.createPriceLine({
            price: trade.take_profit_price,
            color: '#00FF00', // SUPER BRIGHT GREEN - IMPOSSIBLE TO MISS
            lineWidth: 6,
            lineStyle: 0, // Solid
            axisLabelVisible: true,
            title: `TARGET ${trade.take_profit_price.toFixed(decimalPlaces)}`,
            lineVisible: true,
          });
          priceLinesRef.current.push(targetLine);
          console.log(`🔥 CACHE-BUST ${Date.now()}: Created BRIGHT TARGET line at ${trade.take_profit_price.toFixed(5)} for ${trade.instrument} (color: #00FF00)`);
        }

        // Add stop loss price line with custom label - SUPER BRIGHT RED (if valid)
        if (trade.stop_loss_price && !isNaN(trade.stop_loss_price) && trade.stop_loss_price > 0) {
          const stopLine = candlestickSeriesRef.current!.createPriceLine({
            price: trade.stop_loss_price,
            color: '#FF0000', // SUPER BRIGHT RED - IMPOSSIBLE TO MISS
            lineWidth: 8,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: `STOP ${trade.stop_loss_price.toFixed(decimalPlaces)}`,
            lineVisible: true,
          });
          priceLinesRef.current.push(stopLine);
          console.log(`🔥 CACHE-BUST ${Date.now()}: Created BRIGHT STOP line at ${trade.stop_loss_price.toFixed(5)} for ${trade.instrument} (color: #FF0000)`);
        }
        
        // Log chart visible range vs trade prices
        if (candlestickData.length > 0) {
          const candlePrices = candlestickData.map(c => [c.high, c.low]).flat();
          const chartMin = Math.min(...candlePrices);
          const chartMax = Math.max(...candlePrices);
          console.log(`📊 Chart range for ${trade.instrument}: ${chartMin.toFixed(5)} - ${chartMax.toFixed(5)}`);
          console.log(`🎯 Trade levels: Entry ${trade.entry_price.toFixed(5)}, Target ${trade.take_profit_price.toFixed(5)}, Stop ${trade.stop_loss_price.toFixed(5)}`);
          
          // Check if trade levels are within visible range
          const entryInRange = trade.entry_price >= chartMin && trade.entry_price <= chartMax;
          const targetInRange = trade.take_profit_price >= chartMin && trade.take_profit_price <= chartMax;
          const stopInRange = trade.stop_loss_price >= chartMin && trade.stop_loss_price <= chartMax;
          console.log(`🔍 Lines in chart range: Entry ${entryInRange ? '✅' : '❌'}, Target ${targetInRange ? '✅' : '❌'}, Stop ${stopInRange ? '✅' : '❌'}`);
        }

        // Add large directional arrow marker at entry
        if (candlestickData.length > 0) {
          // Find candle closest to entry time or use recent candle
          const entryTime = new Date(trade.open_time).getTime() / 1000;
          let bestCandle = candlestickData[candlestickData.length - 1];
          let bestTimeDiff = Infinity;
          
          // Try to find candle closest to entry time
          for (const candle of candlestickData.slice(-20)) { // Check last 20 candles
            const candleTime = new Date(candle.time).getTime() / 1000;
            const timeDiff = Math.abs(candleTime - entryTime);
            if (timeDiff < bestTimeDiff) {
              bestTimeDiff = timeDiff;
              bestCandle = candle;
            }
          }
          
          const marker = {
            time: (new Date(bestCandle.time).getTime() / 1000) as Time,
            position: trade.direction === 'Long' ? 'belowBar' : 'aboveBar',
            color: colorScheme.entry,
            shape: trade.direction === 'Long' ? 'arrowUp' : 'arrowDown',
            text: trade.direction === 'Long' ? '↑ LONG' : '↓ SHORT',
          };
          markersRef.current.push(marker);
        }
      });
    });

    // Set all markers at once
    if (markersRef.current.length > 0) {
      candlestickSeriesRef.current.setMarkers(markersRef.current);
    }
  };

  // Update chart data when candlestick data changes
  useEffect(() => {
    console.log(`📊 Chart data update for ${currencyPair}:`, {
      hasSeries: !!candlestickSeriesRef.current,
      candleCount: candlestickData.length,
      tradeCount: activeTrades.length,
      selectedStrategies
    });
    
    if (!candlestickSeriesRef.current || candlestickData.length === 0) return;

    // Convert data to TradingView format
    const tvData: TVCandlestickData[] = candlestickData.map(candle => ({
      time: (new Date(candle.time).getTime() / 1000) as any, // Convert to Unix timestamp
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    candlestickSeriesRef.current.setData(tvData);

    // Update current price and price change
    if (candlestickData.length > 0) {
      const latest = candlestickData[candlestickData.length - 1];
      setCurrentPrice(latest.close);
      
      if (candlestickData.length > 1) {
        const previous = candlestickData[candlestickData.length - 2];
        const change = ((latest.close - previous.close) / previous.close) * 100;
        setPriceChange(change);
      }
    }

    // Add trade overlays after chart data is set
    console.log(`🎯 Calling addTradeOverlays for ${currencyPair}`);
    addTradeOverlays();
    
    // Ensure price scale is always visible
    if (chartRef.current) {
      console.log(`📊 Ensuring price scale is visible for ${currencyPair}`);
      chartRef.current.priceScale('right').applyOptions({
        visible: true,
        autoScale: true,
      });
      chartRef.current.timeScale().fitContent();
      
      if (activeTrades.length > 0) {
        // Calculate price range including trade levels
        const filteredTrades = selectedStrategies.length > 0
          ? activeTrades.filter(trade => selectedStrategies.includes(trade.strategy_name))
          : activeTrades;
        
        if (filteredTrades.length > 0) {
          const tradePrices = filteredTrades.flatMap(trade => [
            trade.entry_price,
            trade.take_profit_price || trade.entry_price,
            trade.stop_loss_price || trade.entry_price,
            trade.current_price || trade.entry_price
          ]).filter(price => price && !isNaN(price));
          
          const candlePrices = candlestickData.flatMap(candle => [candle.high, candle.low]);
          const allPrices = [...tradePrices, ...candlePrices];
          
          if (allPrices.length > 0) {
            const minPrice = Math.min(...allPrices);
            const maxPrice = Math.max(...allPrices);
            // For non-JPY pairs, ensure minimum range for visible price labels
            const minRange = isJPYPair ? 0.5 : 0.0020; // Minimum range: 0.5 for JPY, 0.002 for others
            const currentRange = maxPrice - minPrice;
            const padding = Math.max(currentRange * 0.15, minRange); // Use larger of 15% padding or min range
            
            console.log(`📊 Force-scaling ${isJPYPair ? 'JPY' : 'non-JPY'} chart for ${currencyPair}: ${minPrice.toFixed(decimalPlaces)} - ${maxPrice.toFixed(decimalPlaces)} (range: ${currentRange.toFixed(decimalPlaces)}, padding: ${padding.toFixed(decimalPlaces)})`);
            
            // Keep price scale stable - don't change margins dynamically
            try {
              console.log(`📊 Ensuring stable price scale for ${currencyPair}`);
              // Just ensure the price scale is visible and working
              chartRef.current.priceScale('right').applyOptions({
                visible: true,
                autoScale: true,
              });
              console.log(`✅ Applied stable scaling for ${currencyPair}`);
            } catch (e) {
              console.error('Price scaling failed for', currencyPair, e);
            }
          }
        }
        
        chartRef.current.timeScale().fitContent();
      } else {
        // No trades, just fit the candlestick data but ensure minimum range for non-JPY pairs
        if (chartRef.current) {
          if (!isJPYPair && candlestickData.length > 0) {
            // For non-JPY pairs without trades, still ensure good y-axis scaling
            const candlePrices = candlestickData.flatMap(candle => [candle.high, candle.low]);
            const minPrice = Math.min(...candlePrices);
            const maxPrice = Math.max(...candlePrices);
            const range = maxPrice - minPrice;
            const minRange = 0.0020; // Minimum 20 pips range
            
            // Always ensure price scale is visible
            chartRef.current.priceScale('right').applyOptions({
              visible: true,
              autoScale: true,
            });
            console.log(`📊 Applied basic scaling for ${currencyPair} without trades`);
          }
          
        }
      }
    }
  }, [candlestickData, activeTrades, selectedStrategies]);

  // Fetch active trades
  useEffect(() => {
    console.log(`🔍 Setting up active trades fetch for ${currencyPair}`);
    
    const fetchActiveTrades = async () => {
      try {
        console.log(`📡 Fetching active trades for ${currencyPair}...`);
        const response = await api.getActiveTradesFromRDS();
        
        if (response.success && response.data) {
          console.log(`✅ Got ${response.data.length} total trades, filtering for ${currencyPair}`);
          
          // Filter trades for this currency pair
          const pairTrades = response.data.filter((trade: ActiveTrade) => 
            trade.instrument === currencyPair
          );
          
          console.log(`🎯 Found ${pairTrades.length} trades for ${currencyPair}:`, pairTrades.map(t => ({
            id: t.trade_id,
            instrument: t.instrument,
            strategy: t.strategy_name,
            direction: t.direction
          })));
          
          setActiveTrades(pairTrades);
        } else {
          console.log(`⚠️ RDS API returned unsuccessful response for ${currencyPair}:`, response.error);
          setActiveTrades([]);
        }
      } catch (err) {
        console.error(`❌ Error fetching active trades for ${currencyPair}:`, err);
        setActiveTrades([]);
      }
    };

    fetchActiveTrades();
    
    // Refresh trades every 30 seconds
    const interval = setInterval(fetchActiveTrades, 30000);
    
    return () => clearInterval(interval);
  }, [currencyPair]);

  // Fetch candlestick data
  useEffect(() => {
    let mounted = true;
    
    const fetchCandlestickData = async (retryCount = 0) => {
      if (!mounted) return;
      
      try {
        setLoading(true);
        if (retryCount === 0) setError(null);

        // Add delay between API calls to avoid rate limiting
        if (retryCount > 0) {
          await new Promise(resolve => setTimeout(resolve, Math.min(1000 * retryCount, 5000)));
        }

        // Fetch 100 candlesticks from Redis via Lambda API
        console.log(`🎯 TRADINGVIEW WITH TRADES: ${currencyPair} requesting 100 candles`);
        const response = await api.getCandlestickData(currencyPair, timeframe, 100);
        
        if (!mounted) return;
        
        if (!response.success) {
          throw new Error(response.error || 'Failed to fetch data');
        }

        const data = response;
        
        if (data.success && data.data && Array.isArray(data.data) && data.data.length > 0) {
          // Convert Lambda response format to component format
          const formattedData = data.data.map((candle: any) => ({
            time: candle.datetime || candle.time,
            open: parseFloat(candle.open),
            high: parseFloat(candle.high),
            low: parseFloat(candle.low),
            close: parseFloat(candle.close),
            volume: candle.volume || 0
          })).filter(candle => 
            !isNaN(candle.open) && !isNaN(candle.high) && 
            !isNaN(candle.low) && !isNaN(candle.close)
          );
          
          if (formattedData.length > 0) {
            console.log(`📊 Received ${formattedData.length} candlesticks for ${currencyPair} (requested 100)`);
            setCandlestickData(formattedData);
            setError(null);
          } else {
            throw new Error('No valid candlestick data');
          }
        } else {
          throw new Error(data.error || 'No candlestick data available');
        }
      } catch (err: any) {
        if (!mounted) return;
        
        console.error(`Error fetching candlestick data for ${currencyPair}:`, err);
        
        // Retry logic for common errors
        if (retryCount < 2 && (
          err.message?.includes('CORS') || 
          err.message?.includes('Network') || 
          err.message?.includes('500') ||
          err.message?.includes('Failed to fetch')
        )) {
          console.log(`Retrying ${currencyPair} (attempt ${retryCount + 1}/3)...`);
          fetchCandlestickData(retryCount + 1);
          return;
        }
        
        setError(`Failed to load data (${retryCount + 1} attempts)`);
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    // Add random delay to stagger API calls for different pairs
    const randomDelay = Math.random() * 2000;
    const delayedFetch = setTimeout(() => fetchCandlestickData(), randomDelay);
    
    // Refresh every 5 minutes with random offset
    const refreshInterval = (5 + Math.random() * 2) * 60 * 1000; // 5-7 minutes
    const interval = setInterval(() => fetchCandlestickData(), refreshInterval);
    
    return () => {
      mounted = false;
      clearTimeout(delayedFetch);
      clearInterval(interval);
    };
  }, [currencyPair, timeframe]);

  // Render trade metrics overlay
  const renderTradeMetrics = () => {
    const filteredTrades = selectedStrategies.length > 0
      ? activeTrades.filter(trade => selectedStrategies.includes(trade.strategy_name))
      : activeTrades;

    if (filteredTrades.length === 0) return null;

    return (
      <div className="absolute top-2 left-2 bg-gray-900/90 p-2 rounded-lg border border-gray-700 text-xs">
        {filteredTrades.map((trade, index) => (
          <div key={trade.trade_id} className="mb-1 last:mb-0">
            <div className="flex items-center gap-2">
              {trade.direction === 'Long' ? (
                <ArrowUp className="w-3 h-3 text-green-400" />
              ) : (
                <ArrowDown className="w-3 h-3 text-red-400" />
              )}
              <span className="text-gray-300">{trade.strategy_name}:</span>
              <span className={trade.pips_moved >= 0 ? 'text-green-400' : 'text-red-400'}>
                {trade.pips_moved >= 0 ? '+' : ''}{trade.pips_moved.toFixed(1)} pips
              </span>
              <span className={trade.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                ${trade.unrealized_pnl >= 0 ? '+' : ''}{trade.unrealized_pnl.toFixed(2)}
              </span>
            </div>
          </div>
        ))}
      </div>
    );
  };

  // Render directional arrows on the right axis
  const renderRightAxisArrows = () => {
    const filteredTrades = selectedStrategies.length > 0
      ? activeTrades.filter(trade => selectedStrategies.includes(trade.strategy_name))
      : activeTrades;

    if (filteredTrades.length === 0 || !currentPrice) return null;

    return (
      <>
        {filteredTrades.map((trade, index) => {
          // Calculate position based on target/entry relationship
          const entryPrice = trade.entry_price;
          const targetPrice = trade.take_profit_price;
          const stopPrice = trade.stop_loss_price;
          
          // Calculate approximate pixel position (rough estimate)
          const chartHeight = height || 400;
          const priceRange = Math.max(entryPrice, targetPrice, stopPrice, currentPrice) - 
                           Math.min(entryPrice, targetPrice, stopPrice, currentPrice);
          const relativePos = priceRange > 0 ? 
            (Math.max(entryPrice, targetPrice, stopPrice, currentPrice) - entryPrice) / priceRange : 0.5;
          const topPosition = (relativePos * chartHeight * 0.8) + 40; // Rough positioning
          
          return (
            <div
              key={`arrow-${trade.trade_id}`}
              className="absolute right-2"
              style={{ top: `${topPosition}px` }}
            >
              <div className="flex items-center">
                <div className={`text-2xl font-bold ${
                  trade.direction === 'Long' ? 'text-green-400' : 'text-red-400'
                }`}>
                  {trade.direction === 'Long' ? '↗' : '↘'}
                </div>
              </div>
            </div>
          );
        })}
      </>
    );
  };

  if (loading) {
    return (
      <div className="bg-gray-900 p-4 rounded-lg border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
            <p className="text-sm text-gray-400">{timeframe} Timeframe</p>
          </div>
          <div className="animate-pulse">
            <div className="h-6 w-20 bg-gray-700 rounded"></div>
          </div>
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="text-gray-500 text-sm">Loading chart...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900 p-4 rounded-lg border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
            <p className="text-sm text-gray-400">{timeframe} Timeframe</p>
          </div>
          <AlertCircle className="w-5 h-5 text-red-400" />
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="text-red-400 text-sm text-center">
            <AlertCircle className="w-8 h-8 mx-auto mb-2" />
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 p-4 rounded-lg border border-gray-700 shadow-lg hover:shadow-xl transition-all duration-200 relative">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
          <p className="text-sm text-gray-400">
            {timeframe} • {candlestickData.length} candles
            {activeTrades.length > 0 && ` • ${activeTrades.length} active trades`}
          </p>
        </div>
        <div className="text-right">
          {currentPrice && (
            <>
              <div className="text-lg font-semibold text-white">
                {currentPrice.toFixed(decimalPlaces)}
              </div>
              {priceChange !== null && (
                <div className={`flex items-center justify-end gap-1 text-sm ${priceChange >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {priceChange >= 0 ? (
                    <TrendingUp className="w-4 h-4" />
                  ) : (
                    <TrendingDown className="w-4 h-4" />
                  )}
                  <span>{priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      
      <div className="relative">
        <div ref={chartContainerRef} style={{ height: `${height}px` }} />
        {renderTradeMetrics()}
        
      </div>
      
      <div className="mt-2 text-xs text-gray-500 text-center">
        ⚡ Enhanced TradingView with Trade Overlays • Real-time data from Redis • 100 Candles
      </div>
    </div>
  );
};

export default LightweightTradingViewChartWithTrades;