import React, { useState } from 'react';
import { Server, Database, Cloud, Shield, Zap, ArrowRight, Clock, HardDrive } from 'lucide-react';

const ArchitecturePage = () => {
  const [selectedComponent, setSelectedComponent] = useState<string | null>(null);
  const [hoveredFlow, setHoveredFlow] = useState<string | null>(null);

  const components = {
    'oanda-api': {
      name: 'OANDA API',
      type: 'external',
      icon: <Cloud className="w-6 h-6" />,
      description: 'External forex trading API - Source of truth for all market data and trades',
      details: [
        'v20 REST API for market data',
        'Account information & positions',
        'Real-time pricing streams',
        'Trade execution endpoints'
      ]
    },
    'central-collector': {
      name: 'Central Data Collector',
      type: 'lambda',
      icon: <Zap className="w-6 h-6" />,
      description: 'Single point of OANDA API access - Currently integrating with 15 strategies',
      details: [
        'Individual strategy functions access OANDA directly',
        'Redis integration layer operational',
        'Real-time data writes to Redis hot storage',
        'Proof of concept: str1_Penny_Curve_Strategy working'
      ]
    },
    'redis-hot': {
      name: 'Redis Hot Storage',
      type: 'cache',
      icon: <Zap className="w-6 h-6" />,
      description: 'Sub-second access for real-time trading decisions - OPERATIONAL',
      details: [
        '1 Redis cluster (lumisignals-prod-redis-pg17)',
        'Real-time trade signals and executions',
        'Active trades from strategy functions',
        'Dashboard data source (replacing dummy data)'
      ]
    },
    'trading-strategies': {
      name: '15 Trading Strategies',
      type: 'lambda-group',
      icon: <Server className="w-6 h-6" />,
      description: 'Autonomous trading algorithms - 1 Redis-integrated, 14 pending integration',
      details: [
        'Penny Curve strategies (H1, M15, M5) - 7 functions',
        'Quarter Curve strategies (H1, H2) - 3 functions',
        'Dime Curve strategies (H1, H4) - 3 functions',
        'Custom high-frequency strategies - 2 functions'
      ]
    },
    'rds-warm': {
      name: 'PostgreSQL Warm Storage',
      type: 'database',
      icon: <Database className="w-6 h-6" />,
      description: '90-day retention for analysis and backtesting',
      details: [
        'Historical trade data',
        'Strategy performance metrics',
        'Market data archive',
        'Compliance & audit trails'
      ]
    },
    's3-cold': {
      name: 'S3 Cold Storage',
      type: 'storage',
      icon: <HardDrive className="w-6 h-6" />,
      description: 'Long-term archival for regulatory compliance',
      details: [
        'Automated lifecycle policies',
        'Compressed historical data',
        'Disaster recovery backups',
        'Cost-optimized storage'
      ]
    },
    'secrets-manager': {
      name: 'AWS Secrets Manager',
      type: 'security',
      icon: <Shield className="w-6 h-6" />,
      description: 'Centralized credential management',
      details: [
        'OANDA API credentials',
        'Database connection strings',
        'Redis authentication tokens',
        'Automatic rotation'
      ]
    },
    'dashboard-api': {
      name: 'Dashboard API',
      type: 'lambda',
      icon: <Zap className="w-6 h-6" />,
      description: 'Serves real-time data to pipstop.org dashboard - OPERATIONAL',
      details: [
        'lumisignals-dashboard-data-reader function',
        'Reading live trades from Redis (no more dummy data)',
        'Real-time endpoints: /active-trades, /redis-data',
        'Successfully showing EUR_USD trades from strategy'
      ]
    },
    'pipstop-dashboard': {
      name: 'PipStop Dashboard',
      type: 'frontend',
      icon: <Cloud className="w-6 h-6" />,
      description: 'Real-time trading dashboard at pipstop.org',
      details: [
        'Live trade monitoring',
        'Strategy performance analysis',
        'Risk management tools',
        'Portfolio overview'
      ]
    }
  };

  const dataFlows = [
    {
      id: 'oanda-to-collector',
      from: 'oanda-api',
      to: 'central-collector',
      label: 'Market Data & Trades',
      color: 'text-green-500',
      description: 'Single API connection reduces costs and improves reliability'
    },
    {
      id: 'collector-to-redis',
      from: 'central-collector',
      to: 'redis-hot',
      label: 'Hot Data Distribution',
      color: 'text-red-500',
      description: 'Real-time data distribution to all trading strategies'
    },
    {
      id: 'redis-to-strategies',
      from: 'redis-hot',
      to: 'trading-strategies',
      label: 'Sub-second Access',
      color: 'text-blue-500',
      description: '26 strategies access shared cache instead of individual API calls'
    },
    {
      id: 'collector-to-rds',
      from: 'central-collector',
      to: 'rds-warm',
      label: 'Historical Storage',
      color: 'text-purple-500',
      description: 'Persistent storage for analysis and backtesting'
    },
    {
      id: 'rds-to-s3',
      from: 'rds-warm',
      to: 's3-cold',
      label: 'Archive Policy',
      color: 'text-gray-500',
      description: 'Automated lifecycle management for long-term storage'
    },
    {
      id: 'rds-to-dashboard',
      from: 'rds-warm',
      to: 'dashboard-api',
      label: 'Analytics Data',
      color: 'text-orange-500',
      description: 'Historical data for dashboard analytics'
    },
    {
      id: 'dashboard-to-frontend',
      from: 'dashboard-api',
      to: 'pipstop-dashboard',
      label: 'Live Dashboard',
      color: 'text-teal-500',
      description: 'Real-time updates to trading dashboard'
    }
  ];

  const getComponentStyle = (type: string) => {
    const baseStyle = "relative p-4 rounded-lg border-2 cursor-pointer transition-all duration-200 hover:scale-105";
    
    switch (type) {
      case 'external':
        return `${baseStyle} bg-yellow-50 border-yellow-300 hover:border-yellow-400`;
      case 'lambda':
      case 'lambda-group':
        return `${baseStyle} bg-orange-50 border-orange-300 hover:border-orange-400`;
      case 'cache':
        return `${baseStyle} bg-red-50 border-red-300 hover:border-red-400`;
      case 'database':
        return `${baseStyle} bg-blue-50 border-blue-300 hover:border-blue-400`;
      case 'storage':
        return `${baseStyle} bg-green-50 border-green-300 hover:border-green-400`;
      case 'security':
        return `${baseStyle} bg-purple-50 border-purple-300 hover:border-purple-400`;
      case 'frontend':
        return `${baseStyle} bg-teal-50 border-teal-300 hover:border-teal-400`;
      default:
        return `${baseStyle} bg-gray-50 border-gray-300 hover:border-gray-400`;
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white">
      {/* Header */}
      <div className="bg-black/50 backdrop-blur-sm border-b border-gray-700 p-6">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold mb-2">LumiSignals Architecture</h1>
              <p className="text-gray-300">AWS Serverless Trading System - Data Flow Visualization</p>
            </div>
            <a 
              href="/" 
              className="text-blue-400 hover:text-blue-300 transition-colors"
            >
              ← Back to Dashboard
            </a>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-6">
        {/* Architecture Overview */}
        <div className="mb-8">
          <h2 className="text-2xl font-semibold mb-4">Current Implementation Status</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-green-900/30 rounded-lg p-4 border border-green-500">
              <h3 className="font-semibold text-lg mb-2">✅ Redis Integration</h3>
              <p className="text-gray-300">Real trading data now flowing to dashboard (no more dummy data)</p>
            </div>
            <div className="bg-yellow-900/30 rounded-lg p-4 border border-yellow-500">
              <h3 className="font-semibold text-lg mb-2">🔄 In Progress</h3>
              <p className="text-gray-300">1 of 15 strategy functions Redis-integrated, 14 pending</p>
            </div>
            <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500">
              <h3 className="font-semibold text-lg mb-2">🎯 Architecture</h3>
              <p className="text-gray-300">Strategy → Redis → Dashboard data flow operational</p>
            </div>
          </div>
        </div>

        {/* Interactive Architecture Diagram */}
        <div className="bg-gray-800 rounded-lg p-6 mb-8">
          <h2 className="text-2xl font-semibold mb-6">Interactive Architecture Diagram</h2>
          
          {/* Component Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6 mb-8">
            {Object.entries(components).map(([key, component]) => (
              <div
                key={key}
                className={getComponentStyle(component.type)}
                onClick={() => setSelectedComponent(key)}
              >
                <div className="flex items-center space-x-3 mb-2">
                  {component.icon}
                  <h3 className="font-semibold text-gray-900">{component.name}</h3>
                </div>
                <p className="text-sm text-gray-600 mb-3">{component.description}</p>
                
                {/* Component Type Badge */}
                <div className="flex justify-between items-center">
                  <span className="px-2 py-1 bg-gray-200 text-xs rounded-full text-gray-700">
                    {component.type}
                  </span>
                  {key === 'trading-strategies' && (
                    <span className="text-xs font-bold text-orange-600">15 Functions</span>
                  )}
                  {key === 'redis-hot' && (
                    <span className="text-xs font-bold text-red-600">1 Cluster ✓</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Data Flow Legend */}
        <div className="bg-gray-800 rounded-lg p-6 mb-8">
          <h2 className="text-2xl font-semibold mb-4">Data Flow Patterns</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {dataFlows.map((flow) => (
              <div
                key={flow.id}
                className="flex items-center space-x-3 p-3 rounded-lg bg-gray-700 cursor-pointer hover:bg-gray-600 transition-colors"
                onMouseEnter={() => setHoveredFlow(flow.id)}
                onMouseLeave={() => setHoveredFlow(null)}
              >
                <ArrowRight className={`w-5 h-5 ${flow.color}`} />
                <div>
                  <p className="font-medium">{flow.label}</p>
                  <p className="text-sm text-gray-300">{flow.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Hot/Warm/Cold Storage Strategy */}
        <div className="bg-gray-800 rounded-lg p-6 mb-8">
          <h2 className="text-2xl font-semibold mb-4">Storage Strategy</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-red-900/30 rounded-lg p-4 border border-red-500">
              <div className="flex items-center space-x-2 mb-3">
                <Zap className="w-5 h-5 text-red-400" />
                <h3 className="font-semibold text-red-400">Hot Storage (Redis) ✅ LIVE</h3>
              </div>
              <ul className="text-sm space-y-1 text-gray-300">
                <li>• Real-time trade signals & executions</li>
                <li>• Active trades data for dashboard</li>
                <li>• Strategy performance metrics</li>
                <li>• lumisignals-prod-redis-pg17 cluster</li>
              </ul>
            </div>
            
            <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500">
              <div className="flex items-center space-x-2 mb-3">
                <Database className="w-5 h-5 text-blue-400" />
                <h3 className="font-semibold text-blue-400">Warm Storage (PostgreSQL)</h3>
              </div>
              <ul className="text-sm space-y-1 text-gray-300">
                <li>• 90-day retention</li>
                <li>• Historical analysis</li>
                <li>• Strategy backtesting</li>
                <li>• Dashboard analytics</li>
              </ul>
            </div>
            
            <div className="bg-green-900/30 rounded-lg p-4 border border-green-500">
              <div className="flex items-center space-x-2 mb-3">
                <HardDrive className="w-5 h-5 text-green-400" />
                <h3 className="font-semibold text-green-400">Cold Storage (S3)</h3>
              </div>
              <ul className="text-sm space-y-1 text-gray-300">
                <li>• Long-term archival</li>
                <li>• Automated lifecycle</li>
                <li>• Compliance storage</li>
                <li>• Disaster recovery</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Security Architecture */}
        <div className="bg-gray-800 rounded-lg p-6 mb-8">
          <h2 className="text-2xl font-semibold mb-4">Security Architecture</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <h3 className="font-semibold text-lg">Credential Management</h3>
              <ul className="space-y-2 text-gray-300">
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>AWS Secrets Manager for all credentials</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>No hardcoded API keys in Lambda functions</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>Automatic credential rotation</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>IAM roles with least privilege</span>
                </li>
              </ul>
            </div>
            
            <div className="space-y-4">
              <h3 className="font-semibold text-lg">Network Security</h3>
              <ul className="space-y-2 text-gray-300">
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>VPC isolation for database access</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>API Gateway rate limiting</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>CloudTrail audit logging</span>
                </li>
                <li className="flex items-center space-x-2">
                  <Shield className="w-4 h-4 text-purple-400" />
                  <span>Encrypted data at rest and in transit</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Visual Flow Chart */}
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-2xl font-semibold mb-6">System Flow Chart</h2>
          <div className="bg-gray-900 rounded-lg p-8 overflow-x-auto">
            <svg viewBox="0 0 1200 800" className="w-full h-auto min-w-[1200px]">
              {/* Background Grid */}
              <defs>
                <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#374151" strokeWidth="1" opacity="0.3"/>
                </pattern>
                
                {/* Arrow Markers */}
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#60A5FA" />
                </marker>
                
                <marker id="arrowhead-green" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#34D399" />
                </marker>
                
                <marker id="arrowhead-orange" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#FB923C" />
                </marker>
                
                <marker id="arrowhead-purple" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#A78BFA" />
                </marker>
              </defs>
              
              <rect width="1200" height="800" fill="url(#grid)" />
              
              {/* Components */}
              
              {/* OANDA API */}
              <g id="oanda-api">
                <rect x="50" y="50" width="140" height="80" rx="10" fill="#FEF3C7" stroke="#F59E0B" strokeWidth="2" />
                <text x="120" y="80" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">OANDA API</text>
                <text x="120" y="100" textAnchor="middle" className="fill-gray-600 text-xs">External Source</text>
              </g>
              
              {/* Secrets Manager */}
              <g id="secrets-manager">
                <rect x="50" y="200" width="140" height="80" rx="10" fill="#EDE9FE" stroke="#8B5CF6" strokeWidth="2" />
                <text x="120" y="230" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">AWS Secrets</text>
                <text x="120" y="250" textAnchor="middle" className="fill-gray-600 text-xs">Manager</text>
              </g>
              
              {/* Central Data Collector */}
              <g id="central-collector">
                <rect x="300" y="50" width="140" height="80" rx="10" fill="#FED7AA" stroke="#F97316" strokeWidth="2" />
                <text x="370" y="80" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">Central Data</text>
                <text x="370" y="100" textAnchor="middle" className="fill-gray-600 text-xs">Collector (Lambda)</text>
              </g>
              
              {/* Redis Hot Storage */}
              <g id="redis-hot">
                <rect x="550" y="50" width="140" height="80" rx="10" fill="#FEE2E2" stroke="#EF4444" strokeWidth="2" />
                <text x="620" y="80" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">Redis Cluster</text>
                <text x="620" y="100" textAnchor="middle" className="fill-gray-600 text-xs">Hot Storage</text>
              </g>
              
              {/* Trading Strategies */}
              <g id="trading-strategies">
                <rect x="800" y="50" width="140" height="80" rx="10" fill="#FED7AA" stroke="#F97316" strokeWidth="2" />
                <text x="870" y="80" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">15 Trading</text>
                <text x="870" y="100" textAnchor="middle" className="fill-gray-600 text-xs">Strategies (Lambda)</text>
              </g>
              
              {/* PostgreSQL RDS */}
              <g id="rds-warm">
                <rect x="550" y="200" width="140" height="80" rx="10" fill="#DBEAFE" stroke="#3B82F6" strokeWidth="2" />
                <text x="620" y="230" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">PostgreSQL</text>
                <text x="620" y="250" textAnchor="middle" className="fill-gray-600 text-xs">Warm Storage</text>
              </g>
              
              {/* S3 Cold Storage */}
              <g id="s3-cold">
                <rect x="550" y="350" width="140" height="80" rx="10" fill="#D1FAE5" stroke="#10B981" strokeWidth="2" />
                <text x="620" y="380" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">S3 Bucket</text>
                <text x="620" y="400" textAnchor="middle" className="fill-gray-600 text-xs">Cold Storage</text>
              </g>
              
              {/* Dashboard API */}
              <g id="dashboard-api">
                <rect x="300" y="500" width="140" height="80" rx="10" fill="#FED7AA" stroke="#F97316" strokeWidth="2" />
                <text x="370" y="530" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">Dashboard API</text>
                <text x="370" y="550" textAnchor="middle" className="fill-gray-600 text-xs">(Lambda)</text>
              </g>
              
              {/* PipStop Dashboard */}
              <g id="pipstop-dashboard">
                <rect x="50" y="500" width="140" height="80" rx="10" fill="#E0F2FE" stroke="#0891B2" strokeWidth="2" />
                <text x="120" y="530" textAnchor="middle" className="fill-gray-800 text-sm font-semibold">PipStop</text>
                <text x="120" y="550" textAnchor="middle" className="fill-gray-600 text-xs">Dashboard</text>
              </g>
              
              {/* Flow Arrows */}
              
              {/* OANDA → Central Collector */}
              <line x1="190" y1="90" x2="300" y2="90" stroke="#34D399" strokeWidth="3" markerEnd="url(#arrowhead-green)" />
              <text x="245" y="80" textAnchor="middle" className="fill-green-400 text-xs font-medium">Market Data</text>
              
              {/* Secrets → Central Collector */}
              <line x1="190" y1="240" x2="300" y2="120" stroke="#A78BFA" strokeWidth="2" markerEnd="url(#arrowhead-purple)" strokeDasharray="5,5" />
              <text x="220" y="180" textAnchor="middle" className="fill-purple-400 text-xs">Credentials</text>
              
              {/* Central Collector → Redis */}
              <line x1="440" y1="90" x2="550" y2="90" stroke="#EF4444" strokeWidth="3" markerEnd="url(#arrowhead)" />
              <text x="495" y="80" textAnchor="middle" className="fill-red-400 text-xs font-medium">Hot Data</text>
              
              {/* Redis → Trading Strategies */}
              <line x1="690" y1="90" x2="800" y2="90" stroke="#60A5FA" strokeWidth="3" markerEnd="url(#arrowhead)" />
              <text x="745" y="80" textAnchor="middle" className="fill-blue-400 text-xs font-medium">Real-time</text>
              
              {/* Central Collector → RDS */}
              <line x1="400" y1="130" x2="580" y2="200" stroke="#3B82F6" strokeWidth="2" markerEnd="url(#arrowhead)" />
              <text x="490" y="165" textAnchor="middle" className="fill-blue-400 text-xs">Historical</text>
              
              {/* RDS → S3 */}
              <line x1="620" y1="280" x2="620" y2="350" stroke="#10B981" strokeWidth="2" markerEnd="url(#arrowhead-green)" />
              <text x="640" y="315" textAnchor="start" className="fill-green-400 text-xs">Archive</text>
              
              {/* RDS → Dashboard API */}
              <line x1="550" y1="240" x2="440" y2="500" stroke="#FB923C" strokeWidth="2" markerEnd="url(#arrowhead-orange)" />
              <text x="495" y="370" textAnchor="middle" className="fill-orange-400 text-xs">Analytics</text>
              
              {/* Dashboard API → PipStop */}
              <line x1="300" y1="540" x2="190" y2="540" stroke="#0891B2" strokeWidth="3" markerEnd="url(#arrowhead)" />
              <text x="245" y="530" textAnchor="middle" className="fill-cyan-400 text-xs font-medium">Live Dashboard</text>
              
              {/* Secrets → Dashboard API */}
              <line x1="120" y1="280" x2="320" y2="500" stroke="#A78BFA" strokeWidth="2" markerEnd="url(#arrowhead-purple)" strokeDasharray="5,5" />
              <text x="180" y="390" textAnchor="middle" className="fill-purple-400 text-xs">API Keys</text>
              
              {/* Data Flow Labels */}
              <g id="flow-labels">
                <rect x="950" y="50" width="200" height="300" fill="#1F2937" stroke="#4B5563" strokeWidth="1" rx="5" />
                <text x="1050" y="80" textAnchor="middle" className="fill-white text-lg font-semibold">Data Flow Legend</text>
                
                <line x1="970" y1="110" x2="1000" y2="110" stroke="#34D399" strokeWidth="3" markerEnd="url(#arrowhead-green)" />
                <text x="1010" y="115" className="fill-green-400 text-sm">OANDA API Calls</text>
                
                <line x1="970" y1="140" x2="1000" y2="140" stroke="#EF4444" strokeWidth="3" />
                <text x="1010" y="145" className="fill-red-400 text-sm">Hot Storage (Redis)</text>
                
                <line x1="970" y1="170" x2="1000" y2="170" stroke="#60A5FA" strokeWidth="3" />
                <text x="1010" y="175" className="fill-blue-400 text-sm">Real-time Access</text>
                
                <line x1="970" y1="200" x2="1000" y2="200" stroke="#3B82F6" strokeWidth="2" />
                <text x="1010" y="205" className="fill-blue-400 text-sm">Historical Data</text>
                
                <line x1="970" y1="230" x2="1000" y2="230" stroke="#10B981" strokeWidth="2" />
                <text x="1010" y="235" className="fill-green-400 text-sm">Archive Process</text>
                
                <line x1="970" y1="260" x2="1000" y2="260" stroke="#FB923C" strokeWidth="2" />
                <text x="1010" y="265" className="fill-orange-400 text-sm">Analytics Feed</text>
                
                <line x1="970" y1="290" x2="1000" y2="290" stroke="#A78BFA" strokeWidth="2" strokeDasharray="5,5" />
                <text x="1010" y="295" className="fill-purple-400 text-sm">Secure Credentials</text>
                
                <line x1="970" y1="320" x2="1000" y2="320" stroke="#0891B2" strokeWidth="3" />
                <text x="1010" y="325" className="fill-cyan-400 text-sm">Dashboard UI</text>
              </g>
              
              {/* Performance Metrics */}
              <g id="metrics">
                <rect x="950" y="400" width="200" height="250" fill="#1F2937" stroke="#4B5563" strokeWidth="1" rx="5" />
                <text x="1050" y="430" textAnchor="middle" className="fill-white text-lg font-semibold">Performance Metrics</text>
                
                <text x="970" y="460" className="fill-green-400 text-sm font-medium">✓ Redis Integration Live</text>
                <text x="970" y="480" className="fill-yellow-400 text-sm">• Real dashboard data operational</text>
                
                <text x="970" y="510" className="fill-red-400 text-sm font-medium">✅ Real Trading Data</text>
                <text x="970" y="530" className="fill-yellow-400 text-sm">• No more dummy data</text>
                
                <text x="970" y="560" className="fill-blue-400 text-sm font-medium">🔄 1 of 15 Strategies</text>
                <text x="970" y="580" className="fill-yellow-400 text-sm">• 14 pending Redis integration</text>
                
                <text x="970" y="610" className="fill-purple-400 text-sm font-medium">🎯 Proof of Concept</text>
                <text x="970" y="630" className="fill-yellow-400 text-sm">• str1_Penny_Curve working</text>
              </g>
              
              {/* Trading Stats */}
              <g id="stats">
                <rect x="50" y="650" width="300" height="100" fill="#1F2937" stroke="#4B5563" strokeWidth="1" rx="5" />
                <text x="200" y="680" textAnchor="middle" className="fill-white text-lg font-semibold">Live Trading Stats</text>
                
                <text x="70" y="710" className="fill-green-400 text-sm font-medium">15 Strategy Functions</text>
                <text x="70" y="730" className="fill-blue-400 text-sm">1 Redis-integrated ✓</text>
                
                <text x="220" y="710" className="fill-orange-400 text-sm font-medium">1 Redis Cluster</text>
                <text x="220" y="730" className="fill-purple-400 text-sm">Real trade data live</text>
              </g>
            </svg>
          </div>
          
          <div className="mt-6 text-center">
            <p className="text-gray-400 text-sm">
              📊 Interactive flow chart showing real-time data movement through your LumiSignals architecture
            </p>
          </div>
        </div>

        {/* Component Details Modal */}
        {selectedComponent && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-gray-800 rounded-lg max-w-lg w-full p-6 border border-gray-700">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-semibold">{components[selectedComponent].name}</h3>
                <button
                  onClick={() => setSelectedComponent(null)}
                  className="text-gray-400 hover:text-white"
                >
                  ✕
                </button>
              </div>
              
              <p className="text-gray-300 mb-4">{components[selectedComponent].description}</p>
              
              <div className="space-y-2">
                <h4 className="font-medium">Key Features:</h4>
                <ul className="space-y-1 text-sm text-gray-300">
                  {components[selectedComponent].details.map((detail, index) => (
                    <li key={index} className="flex items-start space-x-2">
                      <span className="text-blue-400 mt-1">•</span>
                      <span>{detail}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ArchitecturePage;