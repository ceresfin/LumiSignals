import React, { useState, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { 
  TrendingUp, 
  BarChart3, 
  Shield, 
  Zap, 
  Globe, 
  Code,
  ChevronRight,
  Play,
  ExternalLink 
} from 'lucide-react';

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  accent: 'positive' | 'negative' | 'neutral';
}

const FeatureCard: React.FC<FeatureCardProps> = ({ icon, title, description, accent }) => {
  const { effectiveTheme } = useTheme();
  
  const accentColors = {
    light: {
      positive: '#8A9C91',
      negative: '#B4837D', 
      neutral: '#C2A565'
    },
    dark: {
      positive: '#A2C4BA',
      negative: '#D9AAB1',
      neutral: '#C2A565'
    }
  };

  const color = accentColors[effectiveTheme][accent];

  return (
    <div className="group relative">
      <div className="absolute -inset-0.5 bg-gradient-to-r from-pink-600 to-purple-600 rounded-lg blur opacity-0 group-hover:opacity-20 transition duration-300"></div>
      <div className="relative p-6 bg-surface-light dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 transition-all duration-300 hover:shadow-lg dark:hover:shadow-xl">
        <div 
          className="w-12 h-12 rounded-lg flex items-center justify-center mb-4 transition-all duration-300 group-hover:scale-110"
          style={{ backgroundColor: `${color}20`, color }}
        >
          {icon}
        </div>
        <h3 className="text-lg font-semibold text-text-primary-light dark:text-white mb-2">
          {title}
        </h3>
        <p className="text-text-secondary-light dark:text-gray-300 leading-relaxed">
          {description}
        </p>
      </div>
    </div>
  );
};

const LiveDataVisualization: React.FC = () => {
  const { effectiveTheme } = useTheme();
  const [activeIndex, setActiveIndex] = useState(0);
  
  // Simulated live data
  const [data, setData] = useState([
    { pair: 'EUR/USD', value: 1.0842, change: 0.0012, trend: 'up' },
    { pair: 'GBP/USD', value: 1.2456, change: -0.0034, trend: 'down' },
    { pair: 'USD/JPY', value: 149.23, change: 0.45, trend: 'up' },
    { pair: 'AUD/USD', value: 0.6534, change: 0.0008, trend: 'up' },
    { pair: 'USD/CAD', value: 1.3687, change: -0.0023, trend: 'down' },
  ]);

  // Simulate real-time updates
  useEffect(() => {
    const interval = setInterval(() => {
      setData(prev => prev.map(item => ({
        ...item,
        value: item.value + (Math.random() - 0.5) * 0.01,
        change: (Math.random() - 0.5) * 0.01,
        trend: Math.random() > 0.5 ? 'up' : 'down'
      })));
      setActiveIndex(prev => (prev + 1) % 5);
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const theme = effectiveTheme === 'dark' ? {
    background: '#1E1E1E',
    text: '#F1F1F1',
    positive: '#A2C4BA',
    negative: '#D9AAB1',
    border: '#2C2C2C'
  } : {
    background: '#FFFFFF',
    text: '#1D1E1F',
    positive: '#8A9C91',
    negative: '#B4837D',
    border: '#E5E5E5'
  };

  return (
    <div 
      className="rounded-lg border p-6 transition-all duration-300"
      style={{ 
        backgroundColor: theme.background,
        borderColor: theme.border,
        color: theme.text
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-medium opacity-75">Live Market Data</h4>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
          <span className="text-xs opacity-75">Live</span>
        </div>
      </div>
      
      <div className="space-y-3">
        {data.map((item, index) => (
          <div 
            key={item.pair}
            className={`flex items-center justify-between p-3 rounded transition-all duration-300 ${
              index === activeIndex ? 'bg-gray-100 dark:bg-gray-700' : ''
            }`}
          >
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-medium">{item.pair}</span>
              <span className="text-xs opacity-75">
                {index === activeIndex ? 'Updated' : `${index + 1}s ago`}
              </span>
            </div>
            
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm">
                {item.value.toFixed(4)}
              </span>
              <div className="flex items-center gap-1">
                <TrendingUp 
                  className={`w-3 h-3 ${
                    item.trend === 'up' ? 'text-green-500' : 'text-red-500 rotate-180'
                  }`}
                />
                <span 
                  className={`text-xs font-medium ${
                    item.change > 0 ? 'text-green-500' : 'text-red-500'
                  }`}
                >
                  {item.change > 0 ? '+' : ''}{item.change.toFixed(4)}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const InstitutionalHomePage: React.FC = () => {
  const { effectiveTheme } = useTheme();
  
  const features = [
    {
      icon: <TrendingUp className="w-6 h-6" />,
      title: "Real-Time Data",
      description: "Live streaming market data with sub-second latency for 28 major currency pairs",
      accent: 'positive' as const
    },
    {
      icon: <BarChart3 className="w-6 h-6" />,
      title: "Advanced Analytics",
      description: "Sophisticated momentum analysis with machine learning-powered insights",
      accent: 'neutral' as const
    },
    {
      icon: <Shield className="w-6 h-6" />,
      title: "Risk Management",
      description: "Professional risk assessment tools with real-time position monitoring",
      accent: 'negative' as const
    },
    {
      icon: <Zap className="w-6 h-6" />,
      title: "High Performance",
      description: "Optimized for institutional-grade trading with minimal latency",
      accent: 'positive' as const
    },
    {
      icon: <Globe className="w-6 h-6" />,
      title: "Global Markets",
      description: "24/7 coverage of major forex markets with regional analysis",
      accent: 'neutral' as const
    },
    {
      icon: <Code className="w-6 h-6" />,
      title: "API Integration",
      description: "RESTful API and WebSocket connections for seamless integration",
      accent: 'negative' as const
    }
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors duration-300">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-br from-gray-50 via-white to-gray-100 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900 transition-all duration-300">
        <div className="absolute inset-0 bg-grid-pattern opacity-5"></div>
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="pt-20 pb-16 sm:pt-24 sm:pb-20 lg:pt-32 lg:pb-28">
            <div className="text-center mb-16">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-gray-900 dark:text-white mb-6 tracking-tight">
                Professional
                <span className="block text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-purple-600 dark:from-blue-400 dark:to-purple-400">
                  Quantitative Trading
                </span>
                Platform
              </h1>
              
              <p className="text-xl sm:text-2xl text-gray-600 dark:text-gray-300 mb-8 max-w-3xl mx-auto leading-relaxed">
                Advanced momentum analysis for institutional traders with real-time data, 
                professional risk management, and sophisticated analytics.
              </p>
              
              <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
                <button className="inline-flex items-center px-8 py-3 bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
                  Get Started
                  <ChevronRight className="w-5 h-5 ml-2" />
                </button>
                
                <button className="inline-flex items-center px-8 py-3 bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-900 dark:text-white font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
                  <Play className="w-5 h-5 mr-2" />
                  View Demo
                </button>
                
                <button className="inline-flex items-center px-8 py-3 border border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
                  Learn More
                  <ExternalLink className="w-5 h-5 ml-2" />
                </button>
              </div>
            </div>
            
            {/* Live Data Visualization */}
            <div className="max-w-2xl mx-auto">
              <LiveDataVisualization />
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 bg-white dark:bg-gray-800 transition-colors duration-300">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white mb-4">
              Institutional-Grade Features
            </h2>
            <p className="text-xl text-gray-600 dark:text-gray-300 max-w-3xl mx-auto">
              Professional tools designed for serious traders who demand precision, 
              reliability, and advanced analytics.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {features.map((feature, index) => (
              <FeatureCard
                key={index}
                icon={feature.icon}
                title={feature.title}
                description={feature.description}
                accent={feature.accent}
              />
            ))}
          </div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="py-20 bg-gray-50 dark:bg-gray-900 transition-colors duration-300">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
            <div className="p-8">
              <div className="text-4xl font-bold text-blue-600 dark:text-blue-400 mb-2">
                28
              </div>
              <div className="text-gray-600 dark:text-gray-300 font-medium">
                Currency Pairs
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                Complete forex market coverage
              </div>
            </div>
            
            <div className="p-8">
              <div className="text-4xl font-bold text-green-600 dark:text-green-400 mb-2">
                &lt;1ms
              </div>
              <div className="text-gray-600 dark:text-gray-300 font-medium">
                Data Latency
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                Real-time market updates
              </div>
            </div>
            
            <div className="p-8">
              <div className="text-4xl font-bold text-purple-600 dark:text-purple-400 mb-2">
                99.9%
              </div>
              <div className="text-gray-600 dark:text-gray-300 font-medium">
                Uptime
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                Enterprise-grade reliability
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 bg-gradient-to-br from-blue-600 to-purple-700 dark:from-blue-500 dark:to-purple-600 transition-all duration-300">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-6">
            Ready to elevate your trading?
          </h2>
          <p className="text-xl text-blue-100 mb-8 max-w-2xl mx-auto">
            Join professional traders who rely on LumiTrade for sophisticated 
            market analysis and institutional-grade tools.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button className="inline-flex items-center px-8 py-3 bg-white text-blue-600 hover:bg-gray-100 font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
              Start Free Trial
              <ChevronRight className="w-5 h-5 ml-2" />
            </button>
            <button className="inline-flex items-center px-8 py-3 border border-white text-white hover:bg-white hover:text-blue-600 font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
              Contact Sales
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};