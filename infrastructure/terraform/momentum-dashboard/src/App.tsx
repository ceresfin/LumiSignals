// Main LumiSignals Momentum Dashboard - "Pilot's Cockpit" Design
import React, { useState, useMemo } from 'react';
import { MomentumGrid } from './components/momentum/MomentumGrid';
import { MomentumScanner } from './components/momentum/MomentumScanner';
import { PortfolioExposure } from './components/portfolio/PortfolioExposure';
import { SystemHealth } from './components/system/SystemHealth';
import { MarketRegimes } from './components/market/MarketRegimes';
import StrategyDashboard from './components/strategies/StrategyDashboard';
import { CurrencyPairGraphs } from './components/charts/CurrencyPairGraphs';
import { CurrencyPairGraphsWithTrades } from './components/charts/CurrencyPairGraphsWithTrades';
import { CurrencyPairGraphsAnalytics } from './components/charts/CurrencyPairGraphsAnalytics';
import PortfolioOverview from './components/portfolio/PortfolioOverview';
import { 
  TrendingUp, 
  PieChart, 
  Activity, 
  Globe,
  Wifi, 
  WifiOff,
  RefreshCw,
  Settings,
  Zap,
  BarChart3,
  BarChart
} from 'lucide-react';
import './App.css';
import './styles/pipstop-theme.css';
import './styles/lumitrade-theme.css';
import { ThemeProvider } from './contexts/ThemeContext';
import { InstitutionalThemeToggle } from './components/ui/InstitutionalThemeToggle';

type TabType = 'momentum' | 'momentum-scanner' | 'graphs' | 'analytics' | 'portfolio' | 'rds-portfolio' | 'market' | 'system' | 'strategies';

interface TabConfig {
  id: TabType;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const tabs: TabConfig[] = [
  {
    id: 'momentum',
    label: 'Momentum Grid',
    icon: <TrendingUp className="w-5 h-5" />,
    description: 'Real-time momentum analysis of all 28 currency pairs ranked by strength'
  },
  {
    id: 'momentum-scanner',
    label: 'Momentum Scanner',
    icon: <BarChart className="w-5 h-5" />,
    description: '5-timeframe momentum analysis for all 28 pairs - 15m, 60m, 4h, 24h, 48h with currency filtering'
  },
  {
    id: 'graphs',
    label: 'Graphs',
    icon: <BarChart3 className="w-5 h-5" />,
    description: 'Candlestick charts with active trade overlays - 500 H1 candles per pair from tiered storage'
  },
  // TEMPORARILY DISABLED: Analytics tab to focus on debugging Graphs tab
  // {
  //   id: 'analytics',
  //   label: 'Analytics',
  //   icon: <BarChart3 className="w-5 h-5" />,
  //   description: 'Advanced M5 candlestick analysis with backend analytics overlays'
  // },
  {
    id: 'portfolio',
    label: 'Portfolio & Risk',
    icon: <PieChart className="w-5 h-5" />,
    description: 'Currency exposure, position management, and risk analysis'
  },
  {
    id: 'rds-portfolio',
    label: 'Live RDS Portfolio',
    icon: <Activity className="w-5 h-5" />,
    description: 'Real-time positions and exposures from PostgreSQL RDS'
  },
  {
    id: 'strategies',
    label: 'Trading Strategies',
    icon: <Zap className="w-5 h-5" />,
    description: '10 active Lambda strategies with psychological levels and performance metrics'
  },
  {
    id: 'market',
    label: 'Market Regimes',
    icon: <Globe className="w-5 h-5" />,
    description: 'Market sentiment, economic calendar, and macro analysis'
  },
  {
    id: 'system',
    label: 'System Health',
    icon: <Activity className="w-5 h-5" />,
    description: 'Infrastructure monitoring, performance metrics, and operational status'
  }
];

function AppContent() {
  const [activeTab, setActiveTab] = useState<TabType>('rds-portfolio');
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  // Debug: Log available tabs
  React.useEffect(() => {
    console.log('🔍 Available tabs:', tabs.map(t => ({ id: t.id, label: t.label })));
    console.log('🎯 Current active tab:', activeTab);
  }, [activeTab]);

  // TEMPORARILY DISABLED: 5-second connection check causes remounts every 5 seconds
  // Simulate connection status (replace with actual WebSocket status)
  // React.useEffect(() => {
  //   const checkConnection = () => {
  //     // This would be replaced with actual WebSocket connection status
  //     setIsConnected(Math.random() > 0.1); // 90% uptime simulation
  //   };

  //   checkConnection();
  //   const interval = setInterval(checkConnection, 5000);
  //   return () => clearInterval(interval);
  // }, []);
  
  // Set connection to true once and leave it
  React.useEffect(() => {
    setIsConnected(true);
  }, []);

  const currentTab = tabs.find(tab => tab.id === activeTab);

  // Memoize the graphs component to prevent unnecessary re-renders
  const graphsComponent = useMemo(() => (
    <CurrencyPairGraphsWithTrades timeframe="H1" chartHeight={400} />
  ), []); // Empty deps - component never changes

  const renderTabContent = () => {
    switch (activeTab) {
      case 'momentum':
        return <MomentumGrid columns={7} showFilters={true} autoRefresh={true} />;
      case 'momentum-scanner':
        return <MomentumScanner refreshInterval={300000} />;
      case 'graphs':
        // Return memoized component to prevent re-mounting
        return graphsComponent;
      case 'analytics':
        return <CurrencyPairGraphsAnalytics timeframe="M5" chartHeight={400} />;
      case 'strategies':
        return <StrategyDashboard />;
      case 'portfolio':
        return <PortfolioExposure />;
      case 'rds-portfolio':
        return <PortfolioOverview />;
      case 'market':
        return <MarketRegimes />;
      case 'system':
        return <SystemHealth />;
      default:
        return <MomentumGrid columns={7} showFilters={true} autoRefresh={true} />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors duration-200">
      {/* Modern PipStop Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-40">
        <div className="px-6 py-6">
          <div className="flex items-start justify-between">
            {/* Left Side: Brand + Tagline Block */}
            <div className="flex flex-col">
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">PipStop</h1>
              <p className="text-sm text-blue-600 dark:text-blue-400 leading-tight mt-1">Institutional Trading Intelligence</p>
              <p className="text-sm text-gray-600 dark:text-gray-300 mt-0.5">Real-Time Momentum Analysis</p>
            </div>

            {/* Right Side: Status + Controls Block */}
            <div className="flex items-center gap-4">
              {/* Architecture Link */}
              <a 
                href="/architecture" 
                className="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors"
              >
                Architecture
              </a>
              
              {/* Connection Status */}
              <div className={`flex items-center text-sm ${isConnected ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {isConnected ? (
                  <Wifi className="w-4 h-4 mr-1" />
                ) : (
                  <WifiOff className="w-4 h-4 mr-1" />
                )}
                <span>{isConnected ? 'Live Data' : 'Offline'}</span>
              </div>
              
              {/* Last Update */}
              <div className="hidden md:flex items-center text-sm text-gray-500 dark:text-gray-400">
                <RefreshCw className="w-4 h-4 mr-1" />
                <span>Updated {lastUpdate.toLocaleTimeString()}</span>
              </div>

              {/* Theme Toggle Component */}
              <InstitutionalThemeToggle />

              {/* Settings Button */}
              <button className="p-2 text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors">
                <Settings className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Modern Tab Bar Navigation */}
          <nav className="flex gap-6 mt-6 border-b border-gray-200 dark:border-gray-700 text-sm">
            {tabs.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`relative pb-3 transition-all duration-200 ${
                    isActive 
                      ? 'text-gray-900 dark:text-white' 
                      : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white'
                  }`}
                >
                  {tab.label}
                  {isActive && (
                    <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 dark:bg-blue-400 rounded-full" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>


      {/* Main Content */}
      <main className="flex-1 p-6 bg-gray-50 dark:bg-gray-900">
        <div className="max-w-full">
          {/* Tab Content */}
          <div className="transition-opacity duration-300">
            {renderTabContent()}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="backdrop-blur-sm border-t border-gray-200 dark:border-gray-700 px-6 py-4 bg-white/95 dark:bg-gray-800/95">
        <div className="flex items-center justify-between text-sm text-gray-600 dark:text-gray-300">
          <div className="flex items-center space-x-4">
            <span>© 2025 PipStop</span>
            <span>•</span>
            <span>Powered by LumiTrade</span>
          </div>
          
          <div className="flex items-center space-x-4">
            <span>28 Currency Pairs</span>
            <span>•</span>
            <span>Real-time Momentum Analysis</span>
            <span>•</span>
            <span className={isConnected ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
              {isConnected ? 'System Operational' : 'System Offline'}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

// Main App component with Theme Provider
function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}

export default App;