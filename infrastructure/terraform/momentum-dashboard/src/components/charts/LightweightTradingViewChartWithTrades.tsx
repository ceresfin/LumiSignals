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

interface SignalToggle {
  id: string;
  label: string;
  enabled: boolean;
  group: 'priceAction' | 'sentiment' | 'structure';
}

interface LightweightTradingViewChartWithTradesProps {
  currencyPair: string;
  timeframe?: string;
  height?: number;
  selectedStrategies?: string[];
  sortRank?: number;
  onUserInteraction?: () => void;
  preserveZoom?: boolean;
  activeTrades?: ActiveTrade[]; // CRITICAL FIX: Pass trades as props instead of fetching in each component
  enabledSignals?: SignalToggle[];
  signalData?: any;
}

interface InstitutionalLevel {
  price: number;
  type: 'penny' | 'quarter' | 'dime';
  label: string;
}

interface InstitutionalLevelSettings {
  showPennies: boolean;
  showQuarters: boolean;
  showDimes: boolean;
}

// Color schemes for different strategies (brighter, more visible colors)
const STRATEGY_COLORS = [
  { entry: '#00BFFF', target: '#00FF7F', stop: '#FF4500' }, // Bright Blue, Bright Green, Bright Red
  { entry: '#1E90FF', target: '#32CD32', stop: '#DC143C' }, // Dodger Blue, Lime Green, Crimson
  { entry: '#4169E1', target: '#228B22', stop: '#B22222' }, // Royal Blue, Forest Green, Fire Brick
  { entry: '#00CED1', target: '#9ACD32', stop: '#FF6347' }, // Dark Turquoise, Yellow Green, Tomato
];

// Institutional level colors as specified
const INSTITUTIONAL_COLORS = {
  penny: '#FF69B4', // Pink
  quarter: '#00FF00', // Green  
  dime: '#0000FF'   // Blue
};

// Calculate institutional levels based on psychological price points
const calculateInstitutionalLevels = (currentPrice: number, isJPYPair: boolean): InstitutionalLevel[] => {
  const levels: InstitutionalLevel[] = [];
  
  if (!currentPrice || isNaN(currentPrice)) return levels;
  
  if (isJPYPair) {
    // JPY pairs (2 decimal places)
    
    // Dimes: X00.00 levels (every 10.00) - 2 above and below current price
    const currentDime = Math.round(currentPrice / 10) * 10;
    for (let i = -2; i <= 2; i++) {
      const price = currentDime + (i * 10);
      if (price > 0) {
        levels.push({
          price,
          type: 'dime',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
    // Get dime range for quarters
    const minDime = currentDime - 20;
    const maxDime = currentDime + 20;
    
    // Quarters: XX2.50, XX5.00, XX7.50 levels (every 2.50) - all within dime range
    for (let price = Math.ceil(minDime / 2.5) * 2.5; price <= maxDime; price += 2.5) {
      if (price > 0 && price % 10 !== 0) { // Exclude dime levels
        levels.push({
          price,
          type: 'quarter',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
    // Pennies: XX1.00, XX2.00 levels (every 1.00) - 2 above and below current price
    const currentPenny = Math.round(currentPrice);
    for (let i = -2; i <= 2; i++) {
      const price = currentPenny + i;
      if (price > 0 && price % 2.5 !== 0) { // Exclude quarter/dime levels
        levels.push({
          price,
          type: 'penny',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
  } else {
    // Non-JPY pairs (4 decimal places)
    
    // Dimes: X.1000, X.2000 levels (every 0.1000) - 2 above and below current price
    const currentDime = Math.round(currentPrice * 10) / 10;
    for (let i = -2; i <= 2; i++) {
      const price = currentDime + (i * 0.1);
      if (price > 0) {
        levels.push({
          price,
          type: 'dime',
          label: `${price.toFixed(4)}`
        });
      }
    }
    
    // Get dime range for quarters
    const minDime = currentDime - 0.2;
    const maxDime = currentDime + 0.2;
    
    // Quarters: X.X250, X.X500, X.X750 levels (every 0.0250) - all within dime range
    for (let price = Math.ceil(minDime / 0.025) * 0.025; price <= maxDime; price += 0.025) {
      if (price > 0 && (price * 10) % 1 !== 0) { // Exclude dime levels
        levels.push({
          price: Math.round(price * 10000) / 10000, // Fix floating point precision
          type: 'quarter',
          label: `${price.toFixed(4)}`
        });
      }
    }
    
    // Pennies: X.XX10, X.XX20 levels (every 0.0100) - 2 above and below current price
    const currentPenny = Math.round(currentPrice * 100) / 100;
    for (let i = -2; i <= 2; i++) {
      const price = currentPenny + (i * 0.01);
      if (price > 0 && (price * 100) % 2.5 !== 0) { // Exclude quarter/dime levels
        levels.push({
          price: Math.round(price * 10000) / 10000, // Fix floating point precision
          type: 'penny',
          label: `${price.toFixed(4)}`
        });
      }
    }
  }
  
  return levels.sort((a, b) => a.price - b.price);
};

const LightweightTradingViewChartWithTradesComponent: React.FC<LightweightTradingViewChartWithTradesProps> = ({
  currencyPair,
  timeframe = 'H1',
  height = 300,
  selectedStrategies = [],
  sortRank,
  onUserInteraction,
  preserveZoom = false,
  activeTrades = [], // CRITICAL FIX: Use passed trades instead of fetching
  enabledSignals = [],
  signalData = {}
}) => {
  console.log(`🚀 TradingViewChartWithTrades mounted for ${currencyPair}, strategies:`, selectedStrategies);
  
  // Generate unique component ID for tracking
  const componentId = useRef(Math.random().toString(36).substr(2, 9));
  
  // DIAGNOSTIC: Track component mounting and unmounting with detailed timing
  useEffect(() => {
    const mountTime = Date.now();
    console.log(`🟢 MOUNT: ${currencyPair} - ID: ${componentId.current} - Time: ${mountTime} - Strategies: ${selectedStrategies.length}`);
    
    return () => {
      const unmountTime = Date.now();
      const duration = unmountTime - mountTime;
      console.log(`🔴 UNMOUNT: ${currencyPair} - ID: ${componentId.current} - Time: ${unmountTime} - Duration: ${duration}ms`);
      
      // Log abnormally short lifespans (less than 1 second indicates rapid re-mounting)
      if (duration < 1000) {
        console.warn(`⚠️ RAPID UNMOUNT: ${currencyPair} component lived only ${duration}ms - possible re-mount loop`);
      }
    };
  }, [currencyPair, selectedStrategies.length]);

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
  const institutionalLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<any[]>([]);
  
  const [candlestickData, setCandlestickData] = useState<CandlestickData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number | null>(null);
  const [institutionalSettings, setInstitutionalSettings] = useState<InstitutionalLevelSettings>({
    showPennies: false,
    showQuarters: false, 
    showDimes: false
  });
  const [zoomState, setZoomState] = useState<{from: number | null, to: number | null}>({from: null, to: null});

  // Clean up chart on unmount
  useEffect(() => {
    return () => {
      if (chartRef.current) {
        try {
          chartRef.current.remove();
          chartRef.current = null;
        } catch (e) {
          console.warn('Chart already disposed on unmount:', e);
        }
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
      localization: {
        timeFormatter: (timestamp: number) => {
          // Convert Unix timestamp to EST/EDT for both crosshair AND x-axis
          const date = new Date(timestamp * 1000);
          return date.toLocaleString('en-US', { 
            timeZone: 'America/New_York',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
          });
        },
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
    
    // Track when chart was created to prevent false interaction triggers
    const chartCreatedTime = Date.now();

    // Add user interaction tracking with debouncing to prevent false triggers
    if (onUserInteraction) {
      let isUserInteracting = false;
      let interactionTimeout: NodeJS.Timeout;
      
      // Only track actual user interactions, not programmatic updates
      const handleInteraction = () => {
        if (!isUserInteracting) {
          isUserInteracting = true;
          onUserInteraction();
        }
        // Reset flag after a delay
        clearTimeout(interactionTimeout);
        interactionTimeout = setTimeout(() => {
          isUserInteracting = false;
        }, 1000);
      };
      
      // Track when user scrolls, zooms, or pans
      chart.timeScale().subscribeVisibleTimeRangeChange(() => {
        // Only trigger if chart has been rendered for more than 2 seconds
        // This prevents false triggers during initial data load
        if (Date.now() - chartCreatedTime > 2000) {
          handleInteraction();
          // Save current zoom state
          const timeScale = chart.timeScale();
          const visibleRange = timeScale.getVisibleRange();
          if (visibleRange) {
            setZoomState({ from: visibleRange.from as number, to: visibleRange.to as number });
          }
        }
      });

      // Track crosshair interactions (these are always user-initiated)
      chart.subscribeCrosshairMove(() => {
        handleInteraction();
      });
    }

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
      // Don't dispose chart here - it's handled by the unmount cleanup
      // This prevents double disposal which causes "Object is disposed" error
    };
  }, [height, loading, error]);

  // Clear previous price lines and markers
  const clearOverlays = () => {
    if (candlestickSeriesRef.current) {
      try {
        priceLinesRef.current.forEach(line => {
          if (candlestickSeriesRef.current) {
            candlestickSeriesRef.current.removePriceLine(line);
          }
        });
        priceLinesRef.current = [];
        
        institutionalLinesRef.current.forEach(line => {
          if (candlestickSeriesRef.current) {
            candlestickSeriesRef.current.removePriceLine(line);
          }
        });
        institutionalLinesRef.current = [];
        
        // Clear markers
        if (candlestickSeriesRef.current) {
          candlestickSeriesRef.current.setMarkers([]);
        }
        markersRef.current = [];
        
        // Clear signal overlays
        clearSignalOverlays();
      } catch (e) {
        console.warn('Error clearing chart overlays:', e);
      }
    }
  };
  
  // Signal overlay references
  const signalOverlaysRef = useRef<{
    fibonacciLines: IPriceLine[];
    supplyDemandRects: any[];
  }>({
    fibonacciLines: [],
    supplyDemandRects: []
  });
  
  // Clear signal overlays
  const clearSignalOverlays = () => {
    if (candlestickSeriesRef.current) {
      // Clear Fibonacci lines
      signalOverlaysRef.current.fibonacciLines.forEach(line => {
        try {
          candlestickSeriesRef.current?.removePriceLine(line);
        } catch (e) {
          console.warn('Error removing Fibonacci line:', e);
        }
      });
      signalOverlaysRef.current.fibonacciLines = [];
    }
  };
  
  // Add Fibonacci overlay
  const addFibonacciOverlay = (fibData: any) => {
    if (!candlestickSeriesRef.current || !fibData) return;
    
    const mode = fibData.mode || 'standard'; // 'fixed', 'atr', or 'standard'
    console.log(`📐 Adding Fibonacci overlay (${mode} mode):`, fibData);
    
    const { levels, high, low } = fibData;
    const range = high - low;
    
    // Standard Fibonacci retracement levels with colors
    // Use different styling for ATR vs Fixed mode
    const fibLevels = mode === 'atr' ? [
      // ATR mode uses warmer colors (reds/oranges)
      { level: 0.0, color: '#FF0066', label: '0.0% (ATR)' },
      { level: 0.236, color: '#FF6600', label: '23.6% (ATR)' },
      { level: 0.382, color: '#FF9900', label: '38.2% (ATR)' },
      { level: 0.5, color: '#FFCC00', label: '50.0% (ATR)' },
      { level: 0.618, color: '#FF9966', label: '61.8% (ATR)' },
      { level: 0.786, color: '#FF6666', label: '78.6% (ATR)' },
      { level: 1.0, color: '#FF3366', label: '100.0% (ATR)' }
    ] : [
      // Fixed mode uses cooler colors (blues/purples)
      { level: 0.0, color: '#0099FF', label: '0.0%' },
      { level: 0.236, color: '#0066FF', label: '23.6%' },
      { level: 0.382, color: '#3366FF', label: '38.2%' },
      { level: 0.5, color: '#6666FF', label: '50.0%' },
      { level: 0.618, color: '#9966FF', label: '61.8%' },
      { level: 0.786, color: '#CC66FF', label: '78.6%' },
      { level: 1.0, color: '#FF66FF', label: '100.0%' }
    ];
    
    fibLevels.forEach(({ level, color, label }) => {
      const price = low + (range * level);
      
      try {
        const priceLine = candlestickSeriesRef.current.createPriceLine({
          price,
          color,
          lineWidth: mode === 'atr' ? 2 : 1, // ATR lines are thicker
          lineStyle: mode === 'atr' ? 0 : 2, // ATR solid, Fixed dashed
          axisLabelVisible: true,
          title: `Fib ${label}`
        });
        
        signalOverlaysRef.current.fibonacciLines.push(priceLine);
      } catch (e) {
        console.warn('Error adding Fibonacci line:', e);
      }
    });
  };
  
  // Add Supply/Demand overlay
  const addSupplyDemandOverlay = (zones: any[]) => {
    if (!candlestickSeriesRef.current || !zones || zones.length === 0) return;
    
    console.log('📊 Adding Supply/Demand zones:', zones);
    
    zones.forEach(zone => {
      const { type, start, end, strength } = zone;
      const color = type === 'supply' ? 'rgba(255, 0, 0, 0.1)' : 'rgba(0, 255, 0, 0.1)';
      const borderColor = type === 'supply' ? 'rgba(255, 0, 0, 0.3)' : 'rgba(0, 255, 0, 0.3)';
      
      // Create top and bottom lines for the zone
      try {
        const topLine = candlestickSeriesRef.current.createPriceLine({
          price: end,
          color: borderColor,
          lineWidth: 2,
          lineStyle: 0, // Solid
          axisLabelVisible: false,
          title: ''
        });
        
        const bottomLine = candlestickSeriesRef.current.createPriceLine({
          price: start,
          color: borderColor,
          lineWidth: 2,
          lineStyle: 0, // Solid
          axisLabelVisible: false,
          title: ''
        });
        
        signalOverlaysRef.current.fibonacciLines.push(topLine, bottomLine);
      } catch (e) {
        console.warn('Error adding supply/demand zone:', e);
      }
    });
  };
  
  // Add signal overlays based on enabled signals
  const addSignalOverlays = () => {
    if (!enabledSignals || !signalData || enabledSignals.length === 0) {
      console.log(`📊 No signals to overlay for ${currencyPair}`);
      return;
    }
    
    console.log(`📊 Adding signal overlays for ${currencyPair}:`, {
      enabledSignals: enabledSignals.map(s => s.id),
      hasData: !!signalData
    });
    
    // Clear previous signal overlays
    clearSignalOverlays();
    
    enabledSignals.forEach(signal => {
      switch (signal.id) {
        case 'fibonacci':
          // Current simplified Fixed-mode-only Fibonacci
          if (signalData.fibonacci) {
            addFibonacciOverlay(signalData.fibonacci);
          }
          break;
          
        case 'supply-demand':
          if (signalData.supplyDemand?.zones) {
            addSupplyDemandOverlay(signalData.supplyDemand.zones);
          }
          break;
          
        // TODO: Add other signal overlays as they're implemented
        default:
          console.log(`📊 Signal overlay not yet implemented: ${signal.id}`);
          break;
      }
    });
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
            const candleTime = candle.time as number; // candle.time is already Unix timestamp
            const timeDiff = Math.abs(candleTime - entryTime);
            if (timeDiff < bestTimeDiff) {
              bestTimeDiff = timeDiff;
              bestCandle = candle;
            }
          }
          
          const marker = {
            time: bestCandle.time as Time, // bestCandle.time is already Unix timestamp
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

  // Add institutional level overlays
  const addInstitutionalLevels = () => {
    if (!candlestickSeriesRef.current || !currentPrice) return;
    
    // Clear existing institutional lines
    institutionalLinesRef.current.forEach(line => {
      candlestickSeriesRef.current!.removePriceLine(line);
    });
    institutionalLinesRef.current = [];
    
    // Calculate all levels based on current price
    const allLevels = calculateInstitutionalLevels(currentPrice, isJPYPair);
    
    // Filter levels based on user settings
    const enabledLevels = allLevels.filter(level => {
      if (level.type === 'penny' && !institutionalSettings.showPennies) return false;
      if (level.type === 'quarter' && !institutionalSettings.showQuarters) return false;
      if (level.type === 'dime' && !institutionalSettings.showDimes) return false;
      return true;
    });
    
    // Group levels by price to handle overlaps
    const levelsByPrice = new Map<number, InstitutionalLevel[]>();
    enabledLevels.forEach(level => {
      const roundedPrice = Math.round(level.price * 10000) / 10000; // Handle floating point precision
      if (!levelsByPrice.has(roundedPrice)) {
        levelsByPrice.set(roundedPrice, []);
      }
      levelsByPrice.get(roundedPrice)!.push(level);
    });
    
    // Apply hierarchy: Dimes > Quarters > Pennies
    const hierarchyOrder = { 'dime': 3, 'quarter': 2, 'penny': 1 };
    const finalLevels: InstitutionalLevel[] = [];
    
    levelsByPrice.forEach((levelsAtPrice, price) => {
      // Sort by hierarchy priority (highest first)
      levelsAtPrice.sort((a, b) => hierarchyOrder[b.type] - hierarchyOrder[a.type]);
      // Take the highest priority level
      const dominantLevel = levelsAtPrice[0];
      finalLevels.push(dominantLevel);
    });
    
    // Add price lines for final levels (no overlaps)
    finalLevels.forEach(level => {
      const line = candlestickSeriesRef.current!.createPriceLine({
        price: level.price,
        color: INSTITUTIONAL_COLORS[level.type],
        lineWidth: 2,
        lineStyle: 1, // Dotted
        axisLabelVisible: true,
        title: level.label,
        lineVisible: true,
      });
      institutionalLinesRef.current.push(line);
    });
    
    console.log(`🏛️ Added ${finalLevels.length} institutional levels for ${currencyPair}:`, {
      pennies: finalLevels.filter(l => l.type === 'penny').length,
      quarters: finalLevels.filter(l => l.type === 'quarter').length,
      dimes: finalLevels.filter(l => l.type === 'dime').length,
      overlapsResolved: enabledLevels.length - finalLevels.length
    });
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

    // Convert data to TradingView format with ROBUST OANDA timestamp handling
    const tvData: TVCandlestickData[] = candlestickData.map(candle => {
      try {
        // CRITICAL FIX: Robust timestamp conversion for OANDA nanosecond timestamps
        let timeValue = candle.time;
        
        // Ensure we have a valid ISO string + timeframe normalization
        if (typeof timeValue === 'string') {
          // Final cleanup for any remaining nanoseconds
          timeValue = timeValue.replace(/(\.\d{3})\d*(Z?)$/, '$1Z');
          if (!timeValue.endsWith('Z') && !timeValue.includes('+') && !timeValue.includes('-')) {
            timeValue += 'Z';
          }
          
          // NORMALIZE: Ensure consistent timeframe boundaries for TradingView display
          const date = new Date(timeValue);
          switch(timeframe) {
            case 'M5':
              date.setMinutes(Math.floor(date.getMinutes() / 5) * 5, 0, 0);
              break;
            case 'M15': 
              date.setMinutes(Math.floor(date.getMinutes() / 15) * 15, 0, 0);
              break;
            case 'M30':
              date.setMinutes(Math.floor(date.getMinutes() / 30) * 30, 0, 0);
              break;
            case 'H1':
              date.setMinutes(0, 0, 0);
              break;
            case 'D1':
              date.setHours(0, 0, 0, 0);
              break;
            default:
              date.setMinutes(0, 0, 0);
          }
          timeValue = date.toISOString();
        }
        
        // Convert to Unix timestamp for TradingView (seconds since epoch)
        let timestamp: number;
        if (typeof timeValue === 'number') {
          // timeValue is already a Unix timestamp in seconds
          timestamp = timeValue;
        } else {
          // timeValue is an ISO string, convert to Unix timestamp
          timestamp = new Date(timeValue).getTime() / 1000;
        }
        
        // Validate timestamp is reasonable (after year 2000, not more than 1 day in future)
        if (isNaN(timestamp) || timestamp < 946684800 || timestamp > Date.now() / 1000 + 86400) {
          console.error(`🚨 INVALID UNIX TIMESTAMP for ${currencyPair}:`, {
            original: candle.time,
            processed: timeValue,
            timestamp,
            timestampDate: new Date(timestamp * 1000).toISOString()
          });
          return null;
        }
        
        // Additional validation: ensure all OHLC values are valid
        if (!candle.open || !candle.high || !candle.low || !candle.close ||
            isNaN(candle.open) || isNaN(candle.high) || isNaN(candle.low) || isNaN(candle.close) ||
            candle.open <= 0 || candle.high <= 0 || candle.low <= 0 || candle.close <= 0) {
          console.error(`🚨 INVALID OHLC DATA for ${currencyPair}:`, {
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
            time: timeValue
          });
          return null;
        }
        
        // EMERGENCY DEBUG: Only log first few candles to avoid spam
        if (candlestickData.length < 3) {
          console.log(`✅ VALID CANDLE for ${currencyPair}:`, {
            time: timestamp,
            timeISO: new Date(timestamp * 1000).toISOString(),
            open: candle.open,
            close: candle.close,
            originalTime: candle.time
          });
        }
        
        return {
          time: timestamp as any,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        };
      } catch (error) {
        console.error(`🚨 TIMESTAMP CONVERSION ERROR for ${currencyPair}:`, {
          originalTime: candle.time,
          error: error,
          candle: candle
        });
        return null;
      }
    }).filter((candle): candle is TVCandlestickData => 
      candle !== null && 
      typeof candle.time === 'number' &&
      !isNaN(candle.time) &&
      candle.time > 0 &&
      candle.open > 0 && candle.high > 0 && candle.low > 0 && candle.close > 0
    );

    // Save current zoom state before updating data if preserveZoom is true
    let savedVisibleRange: any = null;
    if (preserveZoom && chartRef.current) {
      const timeScale = chartRef.current.timeScale();
      savedVisibleRange = timeScale.getVisibleRange();
    }

    // EMERGENCY DEBUG: Log data before sending to TradingView
    console.log(`🔍 EMERGENCY DEBUG: ${currencyPair} - About to set ${tvData.length} candles to TradingView`);
    console.log(`🔍 First 3 candles:`, tvData.slice(0, 3));
    console.log(`🔍 Last 3 candles:`, tvData.slice(-3));
    
    // Check for duplicate timestamps which cause lightweight-charts to fail
    const timeSet = new Set();
    const duplicateTimestamps = [];
    for (const candle of tvData) {
      if (timeSet.has(candle.time)) {
        duplicateTimestamps.push(candle.time);
      }
      timeSet.add(candle.time);
    }
    
    if (duplicateTimestamps.length > 0) {
      console.error(`🚨 DUPLICATE TIMESTAMPS DETECTED for ${currencyPair}:`, duplicateTimestamps);
      console.error(`🚨 This will cause lightweight-charts to fail with "Value is null" error`);
      // Remove duplicates by keeping only the last occurrence of each timestamp
      const uniqueCandles = [];
      const seenTimes = new Set();
      for (let i = tvData.length - 1; i >= 0; i--) {
        const candle = tvData[i];
        if (!seenTimes.has(candle.time)) {
          seenTimes.add(candle.time);
          uniqueCandles.unshift(candle);
        }
      }
      console.log(`🔧 FIXED: Removed ${tvData.length - uniqueCandles.length} duplicate candles for ${currencyPair}`);
      tvData.length = 0;
      tvData.push(...uniqueCandles);
    }
    
    // Check for any invalid data
    const invalidCandles = tvData.filter(candle => 
      !candle.time || isNaN(candle.time) || 
      !candle.open || !candle.high || !candle.low || !candle.close ||
      candle.open <= 0 || candle.high <= 0 || candle.low <= 0 || candle.close <= 0
    );
    
    if (invalidCandles.length > 0) {
      console.error(`🚨 INVALID CANDLES DETECTED for ${currencyPair}:`, invalidCandles);
      return; // Don't send invalid data to TradingView
    }
    
    try {
      candlestickSeriesRef.current.setData(tvData);
      console.log(`✅ TradingView data set successfully for ${currencyPair}`);
    } catch (error) {
      console.error(`❌ TradingView setData failed for ${currencyPair}:`, error);
      console.error(`❌ Failed data sample:`, tvData.slice(0, 5));
    }

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
    
    // Add signal overlays if enabled
    console.log(`🎯 Calling addSignalOverlays for ${currencyPair}`);
    addSignalOverlays();
    
    // Add institutional levels if enabled
    addInstitutionalLevels();
    
    // Ensure price scale is always visible
    if (chartRef.current) {
      console.log(`📊 Ensuring price scale is visible for ${currencyPair}`);
      chartRef.current.priceScale('right').applyOptions({
        visible: true,
        autoScale: true,
      });
      
      // Restore zoom state if preserveZoom is true, otherwise fit content
      if (preserveZoom && savedVisibleRange) {
        chartRef.current.timeScale().setVisibleRange(savedVisibleRange);
      } else if (!preserveZoom || !savedVisibleRange) {
        chartRef.current.timeScale().fitContent();
      }
      
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
  }, [candlestickData, activeTrades, selectedStrategies, institutionalSettings]);

  // CRITICAL FIX: Active trades now passed as props - no more individual API calls per chart!

  // Fetch candlestick data ONCE on mount (no auto-refresh to prevent re-renders)
  useEffect(() => {
    console.log(`🔍 CANDLESTICK FETCH TRIGGERED for ${currencyPair} - Deps: currencyPair=${currencyPair}, timeframe=${timeframe}`);
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

        // Fetch 500 candlesticks directly from working API
        console.log(`🎯 API CALL: ${currencyPair} - ID: ${componentId.current} - requesting 500 candles from Direct API - Time: ${Date.now()}`);
        const response = await api.getCandlestickData(currencyPair, timeframe, 500);
        
        if (!mounted) return;
        
        if (!response.success) {
          throw new Error(response.error || 'Failed to fetch data');
        }

        const data = response;
        
        if (data.success && data.data && Array.isArray(data.data) && data.data.length > 0) {
          // EMERGENCY DEBUG: Show raw API response format
          console.log(`🔍 RAW OANDA DATA SAMPLE for ${currencyPair} (first 3):`, data.data.slice(0, 3));
          console.log(`🔍 RAW OANDA DATA SAMPLE for ${currencyPair} (last 3):`, data.data.slice(-3));
          
          // Convert Lambda response format to component format with ROBUST OANDA timestamp handling
          const formattedData = data.data.map((candle: any) => {
            // Handle OANDA nanosecond timestamps - convert to ISO string
            let timeValue = candle.datetime || candle.time || candle.timestamp;
            
            // CRITICAL FIX: Handle both Unix timestamps and ISO strings
            if (typeof timeValue === 'number') {
              // timeValue is already a Unix timestamp in seconds, use directly
              return {
                time: timeValue as Time,
                open: parseFloat(candle.open),
                high: parseFloat(candle.high),
                low: parseFloat(candle.low),
                close: parseFloat(candle.close)
              };
            } else if (typeof timeValue === 'string') {
              // OANDA format: "2024-01-01T12:00:00.000000000Z" 
              // Remove nanoseconds completely and ensure proper Z suffix
              timeValue = timeValue.replace(/(\.\d{3})\d*(Z?)$/, '$1Z');
              
              // Fallback: if no Z suffix, add it
              if (!timeValue.endsWith('Z') && !timeValue.includes('+') && !timeValue.includes('-')) {
                timeValue += 'Z';
              }
              
              // NORMALIZE: Round to timeframe boundaries to prevent micro-differences causing re-renders
              const date = new Date(timeValue);
              switch(timeframe) {
                case 'M5':
                  date.setMinutes(Math.floor(date.getMinutes() / 5) * 5, 0, 0);
                  break;
                case 'M15': 
                  date.setMinutes(Math.floor(date.getMinutes() / 15) * 15, 0, 0);
                  break;
                case 'M30':
                  date.setMinutes(Math.floor(date.getMinutes() / 30) * 30, 0, 0);
                  break;
                case 'H1':
                  date.setMinutes(0, 0, 0); // Force to :00:00.000
                  break;
                case 'D1':
                  date.setHours(0, 0, 0, 0); // Force to 00:00:00.000
                  break;
                default:
                  // For unknown timeframes, round to hour boundary as fallback
                  date.setMinutes(0, 0, 0);
              }
              timeValue = date.toISOString();
            }
              
              // EMERGENCY: Additional validation - ensure timeValue is valid ISO format
              try {
                const testDate = new Date(timeValue);
                if (isNaN(testDate.getTime())) {
                  console.error(`🚨 INVALID TIMESTAMP for ${currencyPair}:`, {
                    original: candle.datetime || candle.time || candle.timestamp,
                    processed: timeValue,
                    candle: candle
                  });
                  return null; // Skip invalid timestamp
                }
              } catch (e) {
                console.error(`🚨 TIMESTAMP PARSE ERROR for ${currencyPair}:`, e, timeValue);
                return null; // Skip unparseable timestamp
              }
            
            // Parse and validate price data
            const open = parseFloat(candle.open);
            const high = parseFloat(candle.high);
            const low = parseFloat(candle.low);
            const close = parseFloat(candle.close);
            
            // Validate all price values are valid numbers > 0
            if (isNaN(open) || isNaN(high) || isNaN(low) || isNaN(close) ||
                open <= 0 || high <= 0 || low <= 0 || close <= 0) {
              console.error(`🚨 INVALID PRICE DATA for ${currencyPair}:`, {
                open, high, low, close, candle
              });
              return null; // Skip invalid price data
            }
            
            return {
              time: (typeof timeValue === 'number' ? timeValue : new Date(timeValue).getTime() / 1000) as Time, // Handle both formats
              open,
              high,
              low,
              close,
              volume: candle.volume || 0
            };
          }).filter((candle): candle is NonNullable<typeof candle> => 
            candle !== null && 
            candle.time && 
            typeof candle.time === 'number' &&
            !isNaN(candle.open) && !isNaN(candle.high) && 
            !isNaN(candle.low) && !isNaN(candle.close) &&
            candle.open > 0 && candle.high > 0 && candle.low > 0 && candle.close > 0
          );
          
          if (formattedData.length > 0) {
            console.log(`📊 API SUCCESS: ${currencyPair} - ID: ${componentId.current} - received ${formattedData.length} candlesticks - Time: ${Date.now()}`);
            console.log(`🔍 RAW API DATA SAMPLE for ${currencyPair}:`, data.data.slice(0, 3));
            console.log(`🔍 FORMATTED DATA SAMPLE for ${currencyPair}:`, formattedData.slice(0, 3));
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
        
        console.error(`❌ API ERROR: ${currencyPair} - ID: ${componentId.current} - ${err.message} - Time: ${Date.now()}`);
        console.error(`Full error for ${currencyPair}:`, err);
        
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

    // Add random delay to stagger API calls for different pairs (prevents Lambda overload)
    const randomDelay = Math.random() * 2000;
    const delayedFetch = setTimeout(() => fetchCandlestickData(), randomDelay);
    
    // DISABLED: Auto-refresh interval to prevent infinite re-mounting cycle
    // const refreshInterval = (5 + Math.random() * 2) * 60 * 1000; // 5-7 minutes
    // const interval = setInterval(() => fetchCandlestickData(), refreshInterval);
    
    return () => {
      mounted = false;
      clearTimeout(delayedFetch);
      // clearInterval(interval);
    };
  }, [currencyPair, timeframe]);
  
  // Update signal overlays when enabled signals or signal data changes
  useEffect(() => {
    if (!candlestickSeriesRef.current) return;
    
    console.log(`🔄 Signal overlay update for ${currencyPair}:`, {
      enabledSignalsCount: enabledSignals?.length || 0,
      hasSignalData: !!signalData,
      enabledSignalIds: enabledSignals?.map(s => s.id) || []
    });
    
    // Clear overlays if no signals are enabled
    if (!enabledSignals || enabledSignals.length === 0) {
      console.log(`🧹 Clearing all signal overlays for ${currencyPair} - no signals enabled`);
      clearSignalOverlays();
      return;
    }
    
    // Only add overlays if we have signal data
    if (signalData) {
      addSignalOverlays();
    }
  }, [enabledSignals, signalData, currencyPair]);

  // Render institutional level controls
  const renderInstitutionalControls = () => {
    return (
      <div className="bg-green-800/90 px-3 py-2 rounded-lg border border-green-600 text-xs">
        <div className="text-center text-white mb-2 font-bold">📊 Institutional Levels</div>
        <div className="flex flex-wrap justify-center gap-4">
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={institutionalSettings.showPennies}
              onChange={(e) => setInstitutionalSettings(prev => ({ ...prev, showPennies: e.target.checked }))}
              className="w-3 h-3"
            />
            <span style={{ color: INSTITUTIONAL_COLORS.penny }}>●</span>
            <span className="text-gray-200">Pennies (100 pips)</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={institutionalSettings.showQuarters}
              onChange={(e) => setInstitutionalSettings(prev => ({ ...prev, showQuarters: e.target.checked }))}
              className="w-3 h-3"
            />
            <span style={{ color: INSTITUTIONAL_COLORS.quarter }}>●</span>
            <span className="text-gray-200">Quarters (250 pips)</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={institutionalSettings.showDimes}
              onChange={(e) => setInstitutionalSettings(prev => ({ ...prev, showDimes: e.target.checked }))}
              className="w-3 h-3"
            />
            <span style={{ color: INSTITUTIONAL_COLORS.dime }}>●</span>
            <span className="text-gray-200">Dimes (1000 pips)</span>
          </label>
        </div>
      </div>
    );
  };

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
      {/* Sort Rank Badge */}
      {sortRank && (
        <div className="absolute top-2 left-2 z-10">
          <div className={`flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold text-white ${
            sortRank <= 3 ? 'bg-blue-600' : 
            sortRank <= 10 ? 'bg-green-600' : 
            sortRank <= 20 ? 'bg-pink-600' : 
            'bg-gray-600'
          }`}>
            {sortRank}
          </div>
        </div>
      )}
      
      <div className="flex items-center justify-between mb-4">
        <div className={sortRank ? 'ml-10' : ''}>
          <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
          <p className="text-sm text-gray-400">
            {timeframe} • {candlestickData.length} candles
            {activeTrades.length > 0 && ` • ${activeTrades.length} active trades`}
          </p>
        </div>
        
        <div className="flex-1 flex justify-center mx-4">
          {renderInstitutionalControls()}
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

// CRITICAL FIX: React.memo to prevent unnecessary re-renders and infinite re-mounting
export const LightweightTradingViewChartWithTrades = React.memo(LightweightTradingViewChartWithTradesComponent, (prevProps, nextProps) => {
  // Custom comparison to prevent re-renders when props are functionally the same
  return (
    prevProps.currencyPair === nextProps.currencyPair &&
    prevProps.timeframe === nextProps.timeframe &&
    prevProps.height === nextProps.height &&
    prevProps.sortRank === nextProps.sortRank &&
    prevProps.preserveZoom === nextProps.preserveZoom &&
    JSON.stringify(prevProps.selectedStrategies) === JSON.stringify(nextProps.selectedStrategies) &&
    JSON.stringify(prevProps.activeTrades) === JSON.stringify(nextProps.activeTrades)
  );
});

export default LightweightTradingViewChartWithTrades;