// TradingView-style detailed chart component with real Fargate data
import React, { useEffect, useRef, useState } from 'react';
import { CurrencyPair } from '../../types/momentum';
import { api } from '../../services/api';

interface TradingViewChartProps {
  pair: CurrencyPair;
  height?: number;
  showTradeOverlays?: boolean;
  timeframe?: '15m' | '1h' | '4h' | '1d';
}

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export const TradingViewChart: React.FC<TradingViewChartProps> = ({
  pair,
  height = 400,
  showTradeOverlays = true,
  timeframe = '1h'
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [candlestickData, setCandlestickData] = useState<CandlestickData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch historical data from Fargate Data Orchestrator
  useEffect(() => {
    const fetchHistoricalData = async () => {
      if (!pair?.pair) return;
      
      setLoading(true);
      setError(null);
      
      try {
        // Convert timeframe to Fargate format
        const fargateTimeframe = timeframe === '15m' ? 'M15' : 
                                 timeframe === '1h' ? 'H1' : 
                                 timeframe === '4h' ? 'H4' : 
                                 timeframe === '1d' ? 'D' : 'H1';
        
        console.log(`🔒 Security: Skipping Fargate data fetch for ${pair.pair} - charts disabled for security`);
        
        // Security: Fargate API access removed from frontend
        const response = { success: false, data: null, error: 'Fargate access disabled for security' };
        
        if (response.success && response.data?.historical_data) {
          const rawData = response.data.historical_data;
          
          // Process and format candlestick data
          const processed: CandlestickData[] = rawData.map((candle: any) => ({
            time: candle.timestamp || candle.time,
            open: parseFloat(candle.open),
            high: parseFloat(candle.high),
            low: parseFloat(candle.low),
            close: parseFloat(candle.close),
            volume: candle.volume || 0
          })).sort((a: CandlestickData, b: CandlestickData) => 
            new Date(a.time).getTime() - new Date(b.time).getTime()
          );
          
          setCandlestickData(processed);
          console.log(`✅ Loaded ${processed.length} candlesticks for ${pair.pair}`);
        } else {
          console.log(`⚠️ No Fargate data for ${pair.pair}, using fallback visualization`);
          setCandlestickData([]);
        }
      } catch (err: any) {
        console.log(`❌ Fargate data fetch failed for ${pair.pair}:`, err.message);
        setError(err.message);
        setCandlestickData([]);
      } finally {
        setLoading(false);
      }
    };

    fetchHistoricalData();
  }, [pair?.pair, timeframe]);

  // Render chart with real or fallback data
  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous content
    containerRef.current.innerHTML = '';

    // Create chart container
    const chartDiv = document.createElement('div');
    chartDiv.style.width = '100%';
    chartDiv.style.height = `${height - 100}px`;
    chartDiv.style.background = 'linear-gradient(135deg, #121212 0%, #1a1a1a 100%)';
    chartDiv.style.borderRadius = '8px';
    chartDiv.style.position = 'relative';
    chartDiv.style.border = '1px solid #A2C4BA';

    // Add momentum analysis overlay
    const overlayDiv = document.createElement('div');
    overlayDiv.style.position = 'absolute';
    overlayDiv.style.top = '20px';
    overlayDiv.style.left = '20px';
    overlayDiv.style.right = '20px';
    overlayDiv.style.background = 'rgba(18, 18, 18, 0.9)';
    overlayDiv.style.borderRadius = '6px';
    overlayDiv.style.padding = '12px';
    overlayDiv.style.border = '1px solid rgba(162, 200, 161, 0.3)';

    overlayDiv.innerHTML = `
      <div style="color: #F7F2E6; font-weight: bold; margin-bottom: 8px;">
        ${pair.display_name} - ${timeframe.toUpperCase()} Analysis
      </div>
      <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; font-size: 12px;">
        ${Object.entries(pair.momentum.timeframes).map(([tf, data]) => `
          <div style="text-align: center; padding: 4px; border-radius: 4px; background: ${
            data.direction === 'bullish' ? 
              (data.strength === 'strong' ? '#A2C8A1' : 'rgba(162, 200, 161, 0.6)') :
              (data.strength === 'strong' ? '#CF4505' : 'rgba(207, 69, 5, 0.6)')
          }; color: ${data.direction === 'bullish' && data.strength === 'weak' ? '#121212' : '#F7F2E6'};">
            <div style="font-weight: bold;">${tf}</div>
            <div>${data.direction === 'bullish' ? '↗' : '↘'}</div>
            <div>${data.strength === 'strong' ? 'Strong' : 'Weak'}</div>
          </div>
        `).join('')}
      </div>
      <div style="margin-top: 12px; display: flex; justify-content: space-between; align-items: center;">
        <div style="color: #B6E6C4;">
          <strong>Composite Score:</strong> ${pair.momentum.composite_score.toFixed(1)}
        </div>
        <div style="color: #B6E6C4;">
          <strong>Signal:</strong> 
          <span style="color: ${
            pair.momentum.signal.includes('BULLISH') ? '#A2C8A1' : 
            pair.momentum.signal.includes('BEARISH') ? '#CF4505' : '#B6E6C4'
          };">
            ${pair.momentum.signal.replace('_', ' ')}
          </span>
        </div>
        <div style="color: #B6E6C4;">
          <strong>Confidence:</strong> ${(pair.momentum.confidence * 100).toFixed(0)}%
        </div>
      </div>
    `;

    chartDiv.appendChild(overlayDiv);

    // Add real candlestick chart or enhanced fallback
    const priceArea = document.createElement('div');
    priceArea.style.position = 'absolute';
    priceArea.style.bottom = '20px';
    priceArea.style.left = '20px';
    priceArea.style.right = '20px';
    priceArea.style.height = '60%';
    priceArea.style.background = 'linear-gradient(to right, rgba(162, 196, 186, 0.05), rgba(194, 165, 101, 0.05))';
    priceArea.style.borderRadius = '6px';
    priceArea.style.border = '1px solid rgba(162, 196, 186, 0.3)';

    // Loading or error state
    if (loading) {
      const loadingDiv = document.createElement('div');
      loadingDiv.style.display = 'flex';
      loadingDiv.style.alignItems = 'center';
      loadingDiv.style.justifyContent = 'center';
      loadingDiv.style.height = '100%';
      loadingDiv.style.color = '#A2C4BA';
      loadingDiv.style.fontSize = '14px';
      loadingDiv.innerHTML = '📊 Loading real market data...';
      priceArea.appendChild(loadingDiv);
    } else if (error) {
      const errorDiv = document.createElement('div');
      errorDiv.style.display = 'flex';
      errorDiv.style.alignItems = 'center';
      errorDiv.style.justifyContent = 'center';
      errorDiv.style.height = '100%';
      errorDiv.style.color = '#D9AAB1';
      errorDiv.style.fontSize = '12px';
      errorDiv.innerHTML = `⚠️ Fargate offline: ${error}`;
      priceArea.appendChild(errorDiv);
    } else if (candlestickData.length > 0) {
      // Render real candlestick data
      const candlesDiv = document.createElement('div');
      candlesDiv.style.display = 'flex';
      candlesDiv.style.alignItems = 'end';
      candlesDiv.style.height = '100%';
      candlesDiv.style.padding = '10px';
      candlesDiv.style.gap = '1px';
      candlesDiv.style.overflow = 'hidden';

      // Calculate price range for scaling
      const prices = candlestickData.flatMap(c => [c.open, c.high, c.low, c.close]);
      const minPrice = Math.min(...prices);
      const maxPrice = Math.max(...prices);
      const priceRange = maxPrice - minPrice;

      // Render up to 100 most recent candles
      const recentCandles = candlestickData.slice(-100);
      
      recentCandles.forEach((candleData, index) => {
        const isGreen = candleData.close >= candleData.open;
        
        // Calculate heights and positions
        const highHeight = ((candleData.high - minPrice) / priceRange) * 80 + 10;
        const lowHeight = ((candleData.low - minPrice) / priceRange) * 80 + 10;
        const openHeight = ((candleData.open - minPrice) / priceRange) * 80 + 10;
        const closeHeight = ((candleData.close - minPrice) / priceRange) * 80 + 10;
        
        // Create candle container
        const candleContainer = document.createElement('div');
        candleContainer.style.position = 'relative';
        candleContainer.style.width = '4px';
        candleContainer.style.height = '100%';
        candleContainer.style.display = 'flex';
        candleContainer.style.flexDirection = 'column-reverse';
        
        // Wick (high-low line)
        const wick = document.createElement('div');
        wick.style.position = 'absolute';
        wick.style.left = '1px';
        wick.style.width = '2px';
        wick.style.bottom = `${lowHeight}%`;
        wick.style.height = `${highHeight - lowHeight}%`;
        wick.style.background = isGreen ? '#A2C4BA' : '#D9AAB1';
        wick.style.opacity = '0.8';
        
        // Body (open-close rectangle)
        const body = document.createElement('div');
        body.style.position = 'absolute';
        body.style.left = '0px';
        body.style.width = '4px';
        body.style.bottom = `${Math.min(openHeight, closeHeight)}%`;
        body.style.height = `${Math.abs(closeHeight - openHeight) || 1}%`;
        body.style.background = isGreen ? '#A2C4BA' : '#D9AAB1';
        body.style.border = `1px solid ${isGreen ? '#89B5A8' : '#C7969D'}`;
        body.style.opacity = '0.9';
        
        // Add hover tooltip
        const tooltip = document.createElement('div');
        tooltip.style.position = 'absolute';
        tooltip.style.bottom = '100%';
        tooltip.style.left = '50%';
        tooltip.style.transform = 'translateX(-50%)';
        tooltip.style.background = 'rgba(0, 0, 0, 0.9)';
        tooltip.style.color = '#F7F2E6';
        tooltip.style.padding = '4px 6px';
        tooltip.style.borderRadius = '4px';
        tooltip.style.fontSize = '10px';
        tooltip.style.whiteSpace = 'nowrap';
        tooltip.style.display = 'none';
        tooltip.style.zIndex = '1000';
        tooltip.innerHTML = `
          <div>O: ${candleData.open.toFixed(5)}</div>
          <div>H: ${candleData.high.toFixed(5)}</div>
          <div>L: ${candleData.low.toFixed(5)}</div>
          <div>C: ${candleData.close.toFixed(5)}</div>
          <div style="font-size: 9px; opacity: 0.7">${new Date(candleData.time).toLocaleString()}</div>
        `;
        
        candleContainer.onmouseenter = () => tooltip.style.display = 'block';
        candleContainer.onmouseleave = () => tooltip.style.display = 'none';
        
        candleContainer.appendChild(wick);
        candleContainer.appendChild(body);
        candleContainer.appendChild(tooltip);
        candlesDiv.appendChild(candleContainer);
      });

      priceArea.appendChild(candlesDiv);
      
      // Add data source indicator
      const dataSourceDiv = document.createElement('div');
      dataSourceDiv.style.position = 'absolute';
      dataSourceDiv.style.top = '5px';
      dataSourceDiv.style.right = '10px';
      dataSourceDiv.style.color = '#A2C4BA';
      dataSourceDiv.style.fontSize = '10px';
      dataSourceDiv.style.opacity = '0.7';
      dataSourceDiv.innerHTML = `📡 Live Fargate Data (${candlestickData.length} candles)`;
      priceArea.appendChild(dataSourceDiv);
      
    } else {
      // Enhanced fallback visualization
      const candlesDiv = document.createElement('div');
      candlesDiv.style.display = 'flex';
      candlesDiv.style.alignItems = 'end';
      candlesDiv.style.height = '100%';
      candlesDiv.style.padding = '10px';
      candlesDiv.style.gap = '2px';

      // Generate enhanced sample candlesticks based on momentum
      for (let i = 0; i < 50; i++) {
        const candle = document.createElement('div');
        const isGreen = Math.random() > (pair.momentum.signal.includes('BEARISH') ? 0.3 : 0.6);
        const height = Math.random() * 80 + 10;
        
        candle.style.width = '3px';
        candle.style.height = `${height}%`;
        candle.style.background = isGreen ? '#A2C4BA' : '#D9AAB1';
        candle.style.opacity = '0.6';
        candle.style.borderRadius = '1px';
        candle.style.border = `1px solid ${isGreen ? '#89B5A8' : '#C7969D'}`;
        
        candlesDiv.appendChild(candle);
      }

      priceArea.appendChild(candlesDiv);
      
      // Add demo data indicator
      const demoDiv = document.createElement('div');
      demoDiv.style.position = 'absolute';
      demoDiv.style.top = '5px';
      demoDiv.style.right = '10px';
      demoDiv.style.color = '#D9AAB1';
      demoDiv.style.fontSize = '10px';
      demoDiv.style.opacity = '0.7';
      demoDiv.innerHTML = '📊 Demo Visualization';
      priceArea.appendChild(demoDiv);
    }

    chartDiv.appendChild(priceArea);

    // Add trade overlays if active trades exist
    if (showTradeOverlays && pair.active_trades && pair.active_trades.length > 0) {
      pair.active_trades.forEach((trade, index) => {
        const tradeOverlay = document.createElement('div');
        tradeOverlay.style.position = 'absolute';
        tradeOverlay.style.top = `${150 + index * 30}px`;
        tradeOverlay.style.left = '20px';
        tradeOverlay.style.right = '20px';
        tradeOverlay.style.background = 'rgba(50, 160, 168, 0.1)';
        tradeOverlay.style.border = '1px solid #32A0A8';
        tradeOverlay.style.borderRadius = '4px';
        tradeOverlay.style.padding = '8px';
        tradeOverlay.style.fontSize = '12px';
        tradeOverlay.style.color = '#B6E6C4';

        tradeOverlay.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <strong>${trade.strategy}</strong> - ${trade.position_size > 0 ? 'LONG' : 'SHORT'}
            </div>
            <div style="color: ${trade.unrealized_pnl >= 0 ? '#A2C8A1' : '#CF4505'}; font-weight: bold;">
              ${trade.unrealized_pnl >= 0 ? '+' : ''}$${trade.unrealized_pnl.toFixed(2)}
            </div>
          </div>
          <div style="margin-top: 4px; display: flex; gap: 16px; font-size: 11px;">
            <span>Entry: ${trade.entry_price.toFixed(5)}</span>
            <span>SL: ${trade.stop_loss.toFixed(5)}</span>
            <span>TP: ${trade.take_profit.toFixed(5)}</span>
            <span>R:R 1:${trade.risk_reward_ratio.toFixed(1)}</span>
          </div>
        `;

        chartDiv.appendChild(tradeOverlay);
      });
    }

    containerRef.current.appendChild(chartDiv);

    // Add chart controls
    const controlsDiv = document.createElement('div');
    controlsDiv.style.marginTop = '12px';
    controlsDiv.style.display = 'flex';
    controlsDiv.style.justifyContent = 'space-between';
    controlsDiv.style.alignItems = 'center';
    controlsDiv.style.padding = '8px 12px';
    controlsDiv.style.background = 'rgba(30, 30, 30, 0.8)';
    controlsDiv.style.borderRadius = '6px';
    controlsDiv.style.border = '1px solid #2C2C2C';

    controlsDiv.innerHTML = `
      <div style="display: flex; gap: 8px;">
        ${['15m', '1h', '4h', '1d'].map(tf => `
          <button style="
            padding: 4px 8px; 
            background: ${tf === timeframe ? '#A2C8A1' : 'rgba(162, 200, 161, 0.2)'}; 
            color: ${tf === timeframe ? '#121212' : '#B6E6C4'};
            border: none; 
            border-radius: 4px; 
            font-size: 12px;
            cursor: pointer;
          ">${tf}</button>
        `).join('')}
      </div>
      <div style="color: #B6E6C4; font-size: 12px;">
        Current: ${pair.current_price.toFixed(5)} • 
        Change: <span style="color: ${pair.daily_change >= 0 ? '#A2C8A1' : '#CF4505'};">
          ${pair.daily_change >= 0 ? '+' : ''}${(pair.daily_change_percent * 100).toFixed(2)}%
        </span>
      </div>
    `;

    containerRef.current.appendChild(controlsDiv);

  }, [pair, height, showTradeOverlays, timeframe, candlestickData, loading, error]);

  return (
    <div 
      ref={containerRef}
      className="w-full"
      style={{ height: `${height}px` }}
    />
  );
};