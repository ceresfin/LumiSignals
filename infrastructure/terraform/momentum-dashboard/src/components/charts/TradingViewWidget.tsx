// TradingView Widget Component for Real Charts
import React, { useEffect, useRef, memo } from 'react';

interface TradingViewWidgetProps {
  pair: string;
  width?: number;
  height?: number;
  interval?: string;
  theme?: 'light' | 'dark';
  style?: string;
  locale?: string;
  toolbar_bg?: string;
  enable_publishing?: boolean;
  allow_symbol_change?: boolean;
  container_id?: string;
}

const TradingViewWidget: React.FC<TradingViewWidgetProps> = memo(({
  pair,
  width = 400,
  height = 300,
  interval = "D",
  theme = "dark",
  style = "1",
  locale = "en",
  toolbar_bg = "#f1f3f6",
  enable_publishing = false,
  allow_symbol_change = false,
  container_id
}) => {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Clear any existing content
    if (container.current) {
      container.current.innerHTML = '';
    }

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = `
      {
        "autosize": false,
        "width": ${width},
        "height": ${height},
        "symbol": "FX_IDC:${pair.replace('/', '')}",
        "interval": "${interval}",
        "timezone": "Etc/UTC",
        "theme": "${theme}",
        "style": "${style}",
        "locale": "${locale}",
        "toolbar_bg": "${toolbar_bg}",
        "enable_publishing": ${enable_publishing},
        "allow_symbol_change": ${allow_symbol_change},
        "calendar": false,
        "support_host": "https://www.tradingview.com"
      }`;

    if (container.current) {
      container.current.appendChild(script);
    }

    return () => {
      if (container.current) {
        container.current.innerHTML = '';
      }
    };
  }, [pair, width, height, interval, theme, style, locale, toolbar_bg, enable_publishing, allow_symbol_change]);

  return (
    <div className="tradingview-widget-container" ref={container} id={container_id}>
      <div className="tradingview-widget-container__widget"></div>
    </div>
  );
});

TradingViewWidget.displayName = 'TradingViewWidget';

export default TradingViewWidget;