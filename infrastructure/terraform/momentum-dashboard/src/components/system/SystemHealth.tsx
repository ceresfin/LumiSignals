// System health monitoring component - Tab 3 of the pilot's cockpit
import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { Activity, Database, Wifi, Zap, AlertTriangle, CheckCircle } from 'lucide-react';

// Mock system health data
const mockSystemHealth = {
  overall_status: 'healthy' as const,
  data_collector: {
    status: 'online' as const,
    last_seen: new Date().toISOString(),
    pairs_collected: 28,
    collection_latency_ms: 45,
    uptime_hours: 72.5
  },
  redis: {
    status: 'connected' as const,
    latency_ms: 2.3,
    cache_hit_rate: 94.7,
    memory_usage_percent: 23.1,
    keys_count: 1247
  },
  database: {
    status: 'connected' as const,
    query_latency_ms: 18.5,
    connection_pool_usage: 12,
    storage_used_gb: 2.3
  },
  lambda_functions: {
    total_executions: 15234,
    successful_executions: 14987,
    error_rate: 1.6,
    avg_duration_ms: 1250
  }
};

// Mock performance data for charts
const generatePerformanceData = () => {
  const now = Date.now();
  const data = [];
  for (let i = 23; i >= 0; i--) {
    data.push({
      time: new Date(now - i * 60 * 1000).toLocaleTimeString('en-US', { 
        hour: '2-digit', 
        minute: '2-digit' 
      }),
      redis_latency: Math.random() * 5 + 1,
      db_latency: Math.random() * 30 + 10,
      api_calls: Math.floor(Math.random() * 50 + 100),
      cache_hit_rate: Math.random() * 10 + 90
    });
  }
  return data;
};

export const SystemHealth: React.FC = () => {
  const [performanceData, setPerformanceData] = useState(generatePerformanceData());
  const [lastUpdate, setLastUpdate] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setPerformanceData(generatePerformanceData());
      setLastUpdate(new Date());
    }, 30000); // Update every 30 seconds

    return () => clearInterval(interval);
  }, []);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
      case 'online':
      case 'connected':
        return <CheckCircle className="w-5 h-5" style={{color: '#A2C8A1'}} />;
      case 'warning':
        return <AlertTriangle className="w-5 h-5" style={{color: '#FFE4B3'}} />;
      case 'error':
      case 'offline':
      case 'disconnected':
        return <AlertTriangle className="w-5 h-5" style={{color: '#CF4505'}} />;
      default:
        return <Activity className="w-5 h-5" style={{color: '#B6E6C4'}} />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy':
      case 'online':
      case 'connected':
        return '#A2C8A1';
      case 'warning':
        return '#FFE4B3';
      case 'error':
      case 'offline':
      case 'disconnected':
        return '#CF4505';
      default:
        return '#B6E6C4';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold" style={{color: '#F7F2E6'}}>
          System Health & Performance
        </h2>
        <div className="flex items-center space-x-2 text-sm" style={{color: '#B6E6C4'}}>
          {getStatusIcon(mockSystemHealth.overall_status)}
          <span>Last updated: {lastUpdate.toLocaleTimeString()}</span>
        </div>
      </div>

      {/* Status Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Data Collector Status */}
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <Wifi className="w-5 h-5" style={{color: '#32A0A8'}} />
              <span className="font-medium" style={{color: '#F7F2E6'}}>Data Collector</span>
            </div>
            {getStatusIcon(mockSystemHealth.data_collector.status)}
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Pairs Collected</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.data_collector.pairs_collected}</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Latency</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.data_collector.collection_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Uptime</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.data_collector.uptime_hours.toFixed(1)}h</span>
            </div>
          </div>
        </div>

        {/* Redis Status */}
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <Zap className="w-5 h-5" style={{color: '#32A0A8'}} />
              <span className="font-medium" style={{color: '#F7F2E6'}}>Redis Cache</span>
            </div>
            {getStatusIcon(mockSystemHealth.redis.status)}
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Hit Rate</span>
              <span style={{color: '#A2C8A1'}}>{mockSystemHealth.redis.cache_hit_rate}%</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Latency</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.redis.latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Memory</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.redis.memory_usage_percent}%</span>
            </div>
          </div>
        </div>

        {/* Database Status */}
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <Database className="w-5 h-5" style={{color: '#32A0A8'}} />
              <span className="font-medium" style={{color: '#F7F2E6'}}>PostgreSQL</span>
            </div>
            {getStatusIcon(mockSystemHealth.database.status)}
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Query Time</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.database.query_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Connections</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.database.connection_pool_usage}</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Storage</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.database.storage_used_gb}GB</span>
            </div>
          </div>
        </div>

        {/* Lambda Functions */}
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <Activity className="w-5 h-5" style={{color: '#32A0A8'}} />
              <span className="font-medium" style={{color: '#F7F2E6'}}>Lambda Functions</span>
            </div>
            {getStatusIcon('healthy')}
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Success Rate</span>
              <span style={{color: '#A2C8A1'}}>
                {((mockSystemHealth.lambda_functions.successful_executions / mockSystemHealth.lambda_functions.total_executions) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Avg Duration</span>
              <span style={{color: '#F7F2E6'}}>{mockSystemHealth.lambda_functions.avg_duration_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span style={{color: '#B6E6C4'}}>Error Rate</span>
              <span style={{color: mockSystemHealth.lambda_functions.error_rate > 5 ? '#CF4505' : '#A2C8A1'}}>
                {mockSystemHealth.lambda_functions.error_rate}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Performance Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Latency Chart */}
        <div className="p-6 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <h3 className="text-lg font-semibold mb-4" style={{color: '#F7F2E6'}}>
            System Latency (Last 24 Hours)
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={performanceData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2C2C2C" />
              <XAxis 
                dataKey="time" 
                tick={{fill: '#B6E6C4', fontSize: 12}}
                interval="preserveStartEnd"
              />
              <YAxis 
                tick={{fill: '#B6E6C4', fontSize: 12}}
                label={{ value: 'ms', angle: -90, position: 'insideLeft', style: {textAnchor: 'middle', fill: '#B6E6C4'} }}
              />
              <Tooltip 
                contentStyle={{
                  background: 'rgba(18, 18, 18, 0.95)',
                  border: '1px solid #A2C8A1',
                  borderRadius: '6px',
                  color: '#F7F2E6'
                }}
              />
              <Line 
                type="monotone" 
                dataKey="redis_latency" 
                stroke="#A2C8A1" 
                strokeWidth={2}
                name="Redis"
                dot={false}
              />
              <Line 
                type="monotone" 
                dataKey="db_latency" 
                stroke="#32A0A8" 
                strokeWidth={2}
                name="Database"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* API Calls Chart */}
        <div className="p-6 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <h3 className="text-lg font-semibold mb-4" style={{color: '#F7F2E6'}}>
            API Activity & Cache Performance
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={performanceData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2C2C2C" />
              <XAxis 
                dataKey="time" 
                tick={{fill: '#B6E6C4', fontSize: 12}}
                interval="preserveStartEnd"
              />
              <YAxis 
                yAxisId="left"
                tick={{fill: '#B6E6C4', fontSize: 12}}
                label={{ value: 'Calls', angle: -90, position: 'insideLeft', style: {textAnchor: 'middle', fill: '#B6E6C4'} }}
              />
              <YAxis 
                yAxisId="right"
                orientation="right"
                tick={{fill: '#B6E6C4', fontSize: 12}}
                label={{ value: 'Hit Rate %', angle: 90, position: 'insideRight', style: {textAnchor: 'middle', fill: '#B6E6C4'} }}
              />
              <Tooltip 
                contentStyle={{
                  background: 'rgba(18, 18, 18, 0.95)',
                  border: '1px solid #A2C8A1',
                  borderRadius: '6px',
                  color: '#F7F2E6'
                }}
              />
              <Area 
                yAxisId="left"
                type="monotone" 
                dataKey="api_calls" 
                stroke="#32A0A8" 
                fill="rgba(50, 160, 168, 0.3)"
                name="API Calls"
              />
              <Line 
                yAxisId="right"
                type="monotone" 
                dataKey="cache_hit_rate" 
                stroke="#A2C8A1" 
                strokeWidth={2}
                name="Cache Hit Rate"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* System Logs */}
      <div className="p-6 rounded-lg border" style={{
        background: 'rgba(30, 30, 30, 0.8)',
        borderColor: '#2C2C2C'
      }}>
        <h3 className="text-lg font-semibold mb-4" style={{color: '#F7F2E6'}}>
          Recent System Events
        </h3>
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {[
            { time: '14:23:15', level: 'INFO', message: 'Data collection completed successfully for 28 pairs', component: 'DataCollector' },
            { time: '14:22:48', level: 'INFO', message: 'Redis cache refreshed, hit rate: 94.7%', component: 'Redis' },
            { time: '14:20:12', level: 'WARN', message: 'High API latency detected: 45ms (threshold: 40ms)', component: 'API' },
            { time: '14:18:33', level: 'INFO', message: 'Lambda function execution completed in 1.2s', component: 'Lambda' },
            { time: '14:15:07', level: 'INFO', message: 'Database connection pool optimized, active connections: 12', component: 'Database' }
          ].map((log, index) => (
            <div key={index} className="flex items-center space-x-4 text-sm p-3 rounded border" style={{
              background: 'rgba(44, 44, 44, 0.3)',
              borderColor: '#2C2C2C'
            }}>
              <span style={{color: '#B6E6C4'}}>{log.time}</span>
              <span className={`px-2 py-1 rounded text-xs font-medium ${
                log.level === 'INFO' ? 'bg-blue-600/20 text-blue-300' :
                log.level === 'WARN' ? 'bg-yellow-600/20 text-yellow-300' :
                'bg-red-600/20 text-red-300'
              }`}>
                {log.level}
              </span>
              <span style={{color: '#32A0A8'}} className="font-medium">{log.component}</span>
              <span style={{color: '#F7F2E6'}} className="flex-1">{log.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};