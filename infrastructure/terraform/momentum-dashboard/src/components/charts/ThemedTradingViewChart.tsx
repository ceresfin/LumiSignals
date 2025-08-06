import React, { useEffect, useRef } from 'react';
import { useTheme } from '../../hooks/useTheme';

interface ThemedTradingViewChartProps {
  symbol?: string;
  interval?: string;
  width?: string | number;
  height?: string | number;
  autosize?: boolean;
  timezone?: string;
  locale?: string;
  style?: string;
  hide_side_toolbar?: boolean;
  allow_symbol_change?: boolean;
  save_image?: boolean;
  studies?: string[];
  container_id?: string;
}

export const ThemedTradingViewChart: React.FC<ThemedTradingViewChartProps> = ({
  symbol = "OANDA:EURUSD",
  interval = "5",
  width = "100%",
  height = 400,
  autosize = true,
  timezone = "Etc/UTC",
  locale = "en",
  style = "1",
  hide_side_toolbar = false,
  allow_symbol_change = true,
  save_image = false,
  studies = [],
  container_id
}) => {
  const [theme] = useTheme();
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const containerId = container_id || `tradingview-widget-${Math.random().toString(36).substr(2, 9)}`;
    chartContainerRef.current.id = containerId;

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.async = true;

    script.onload = () => {
      if (window.TradingView) {
        // Clear any existing widget
        if (widgetRef.current) {
          try {
            widgetRef.current.remove();
          } catch (e) {
            // Ignore errors when removing
          }
        }

        // Theme-specific configuration
        const themeConfig = {
          theme: theme,
          toolbar_bg: theme === 'dark' ? '#1E1E1E' : '#FFFFFF',
          studies_overrides: {
            // Chart background
            "paneProperties.background": theme === 'dark' ? '#121212' : '#FAF9F7',
            "paneProperties.backgroundType": "solid",
            
            // Grid
            "paneProperties.vertGridProperties.color": theme === 'dark' ? '#333333' : '#E5E3DF',
            "paneProperties.horzGridProperties.color": theme === 'dark' ? '#333333' : '#E5E3DF',
            
            // Candles
            "mainSeriesProperties.candleStyle.upColor": "#C7D9C5",
            "mainSeriesProperties.candleStyle.downColor": "#C26A6A",
            "mainSeriesProperties.candleStyle.drawWick": true,
            "mainSeriesProperties.candleStyle.drawBorder": true,
            "mainSeriesProperties.candleStyle.borderColor": theme === 'dark' ? '#333333' : '#999999',
            "mainSeriesProperties.candleStyle.borderUpColor": "#C7D9C5",
            "mainSeriesProperties.candleStyle.borderDownColor": "#C26A6A",
            "mainSeriesProperties.candleStyle.wickUpColor": "#C7D9C5",
            "mainSeriesProperties.candleStyle.wickDownColor": "#C26A6A",
            
            // Volume
            "volumePaneSize": "medium",
            "scalesProperties.textColor": theme === 'dark' ? '#B3B3B3' : '#666666',
            "scalesProperties.lineColor": theme === 'dark' ? '#333333' : '#E5E3DF',
          },
          overrides: {
            // Chart background
            "paneProperties.background": theme === 'dark' ? '#121212' : '#FAF9F7',
            "paneProperties.backgroundType": "solid",
            
            // Scales
            "scalesProperties.textColor": theme === 'dark' ? '#B3B3B3' : '#666666',
            "scalesProperties.lineColor": theme === 'dark' ? '#333333' : '#E5E3DF',
            
            // Crosshair
            "crosshairProperties.transparency": 50,
            "crosshairProperties.color": theme === 'dark' ? '#8FC9CF' : '#A2C4BA',
            
            // Watermark
            "mainSeriesProperties.showCountdown": false,
            "mainSeriesProperties.visible": true,
          }
        };

        // Create new widget
        widgetRef.current = new window.TradingView.widget({
          symbol: symbol,
          interval: interval,
          container_id: containerId,
          width: width,
          height: height,
          autosize: autosize,
          timezone: timezone,
          locale: locale,
          style: style,
          hide_side_toolbar: hide_side_toolbar,
          allow_symbol_change: allow_symbol_change,
          save_image: save_image,
          studies: studies,
          ...themeConfig
        });
      }
    };

    chartContainerRef.current.innerHTML = '';
    chartContainerRef.current.appendChild(script);

    return () => {
      if (widgetRef.current) {
        try {
          widgetRef.current.remove();
        } catch (e) {
          // Ignore cleanup errors
        }
      }
    };
  }, [symbol, interval, theme, width, height, autosize, timezone, locale, style, hide_side_toolbar, allow_symbol_change, save_image, studies, container_id]);

  return (
    <div 
      ref={chartContainerRef}
      className="w-full h-full rounded-lg overflow-hidden border border-border-light dark:border-border-dark"
    />
  );
};

export default ThemedTradingViewChart;