// API service for LumiTrade momentum dashboard
import axios, { AxiosInstance, AxiosResponse } from 'axios';
import { ApiResponse, MomentumRanking, PortfolioExposure, SystemHealth } from '../types/momentum';

class ApiService {
  private client: AxiosInstance;
  private rdsClient: AxiosInstance;
  private candlestickClient: AxiosInstance;
  // private fargateClient: AxiosInstance; // REMOVED FOR SECURITY

  constructor() {
    this.client = axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL || 'https://xrlwec390l.execute-api.us-east-1.amazonaws.com/prod',
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // RDS Dashboard API client
    this.rdsClient = axios.create({
      baseURL: import.meta.env.VITE_DASHBOARD_API_URL || 'https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod',
      timeout: 15000,
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': import.meta.env.VITE_DASHBOARD_API_KEY || 'lumi-dash-2025-secure-api-key-renaissance-trading-system',
      },
    });

    // Direct Candlestick API client - bypasses Lambda strategies for pure data serving
    const candlestickApiUrl = import.meta.env.VITE_CANDLESTICK_API_URL || 'https://your-direct-candlestick-api.execute-api.us-east-1.amazonaws.com/prod';
    const candlestickApiKey = import.meta.env.VITE_CANDLESTICK_API_KEY || 'lumi-candlestick-direct-api-key-2025';
    
    console.log(`🚀 Direct Candlestick API initialized: ${candlestickApiUrl}`);
    
    this.candlestickClient = axios.create({
      baseURL: candlestickApiUrl,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': candlestickApiKey,
      },
    });

    // Fargate Data Orchestrator API client - REMOVED FOR SECURITY
    // this.fargateClient = axios.create({
    //   baseURL: import.meta.env.VITE_FARGATE_API_URL || 'http://lumisignals-fargate-alb-1581479607.us-east-1.elb.amazonaws.com:8080',
    //   timeout: 30000,
    //   headers: {
    //     'Content-Type': 'application/json',
    //   },
    // });

    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        // Add any authentication headers here if needed
        console.log(`🔄 API Request: ${config.method?.toUpperCase()} ${config.url}`);
        return config;
      },
      (error) => {
        console.log('⚠️ API Request Setup Error:', error.message);
        return Promise.reject(error);
      }
    );

    // Response interceptor
    this.client.interceptors.response.use(
      (response: AxiosResponse) => {
        console.log(`✅ API Response: ${response.status} ${response.config.url}`);
        return response;
      },
      (error) => {
        // Log but don't treat as fatal error - dashboard should work with demo data
        const errorMsg = error.response?.data?.message || error.message || 'Network error';
        console.log(`ℹ️ API temporarily unavailable: ${errorMsg} - Using demo data instead`);
        return Promise.reject(error);
      }
    );
  }

  // Generic API call method
  private async makeRequest<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    endpoint: string,
    data?: any
  ): Promise<ApiResponse<T>> {
    try {
      const response = await this.client.request({
        method,
        url: endpoint,
        data,
      });

      return {
        success: true,
        data: response.data,
        timestamp: new Date().toISOString(),
      };
    } catch (error: any) {
      return {
        success: false,
        data: {} as T,
        error: error.response?.data?.message || error.message || 'Unknown error occurred',
        timestamp: new Date().toISOString(),
      };
    }
  }

  // RDS Database API call method
  private async makeRDSRequest<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    endpoint: string,
    data?: any
  ): Promise<ApiResponse<T>> {
    try {
      console.log(`🚀 RDS API Request: ${method} ${this.rdsClient.defaults.baseURL}${endpoint}`);
      const response = await this.rdsClient.request({
        method,
        url: endpoint,
        data,
      });

      console.log(`✅ RDS API Response: ${response.status}`, {
        success: response.data?.success,
        hasData: !!response.data?.data,
        dataType: typeof response.data?.data,
        dataLength: Array.isArray(response.data?.data) ? response.data.data.length : 'not array'
      });

      // RDS Lambda returns data in { success: true, data: ... } format
      if (response.data && response.data.success) {
        return {
          success: true,
          data: response.data.data,
          timestamp: response.data.timestamp || new Date().toISOString(),
        };
      } else {
        throw new Error(response.data?.error || 'RDS query failed');
      }
    } catch (error: any) {
      console.error('❌ RDS API Error:', {
        message: error.message,
        status: error.response?.status,
        statusText: error.response?.statusText,
        data: error.response?.data,
        url: `${this.rdsClient.defaults.baseURL}${endpoint}`
      });
      return {
        success: false,
        data: {} as T,
        error: error.response?.data?.error || error.message || 'RDS connection failed',
        timestamp: new Date().toISOString(),
      };
    }
  }

  // Direct Candlestick API call method
  private async makeCandlestickRequest<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    endpoint: string,
    data?: any
  ): Promise<ApiResponse<T>> {
    try {
      const response = await this.candlestickClient.request({
        method,
        url: endpoint,
        data,
      });

      // Direct candlestick API returns data in { success: true, data: ... } format
      if (response.data && response.data.success) {
        return {
          success: true,
          data: response.data.data,
          timestamp: response.data.timestamp || new Date().toISOString(),
        };
      } else {
        return {
          success: false,
          data: {} as T,
          error: response.data?.error || 'Invalid response format',
          timestamp: new Date().toISOString(),
        };
      }
    } catch (error: any) {
      return {
        success: false,
        data: {} as T,
        error: error.response?.data?.error || error.message || 'Candlestick API connection failed',
        timestamp: new Date().toISOString(),
      };
    }
  }

  // Fargate Data Orchestrator API call method - REMOVED FOR SECURITY
  // private async makeFargateRequest<T>(
  //   method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  //   endpoint: string,
  //   data?: any
  // ): Promise<ApiResponse<T>> {
  //   // SECURITY: Fargate access removed from frontend
  //   return {
  //     success: false,
  //     data: {} as T,
  //     error: 'Fargate access disabled for security',
  //     timestamp: new Date().toISOString(),
  //   };
  // }

  // Health check
  async healthCheck(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/api/health');
  }

  // Market data endpoints
  async getMarketData(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/api/market-data');
  }

  async getCandlesticks(pair?: string, timeframe?: string): Promise<ApiResponse<any>> {
    const params = new URLSearchParams();
    if (pair) params.append('pair', pair);
    if (timeframe) params.append('timeframe', timeframe);
    
    const query = params.toString();
    return this.makeRequest('GET', `/api/candlesticks${query ? `?${query}` : ''}`);
  }

  // Momentum analysis endpoints
  async getMomentumRanking(): Promise<ApiResponse<MomentumRanking>> {
    return this.makeRequest('GET', '/api/market-data');
  }

  async getMomentumScannerData(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/api/momentum/scanner');
  }

  async getPortfolioOverview(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=portfolio-overview');
  }

  async getStrategyAnalytics(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=strategy-performance');
  }


  async getSystemHealth(): Promise<ApiResponse<SystemHealth>> {
    return this.makeRequest('GET', '/analytics?type=system-health');
  }

  // Portfolio exposure endpoints
  async getPortfolioExposure(): Promise<ApiResponse<PortfolioExposure>> {
    return this.makeRequest('GET', '/portfolio/exposure');
  }

  async getCurrencyExposure(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/portfolio/currency-exposure');
  }

  // Trading endpoints - CORS FIX: Redirect to working RDS API
  async getActiveTrades(): Promise<ApiResponse<any>> {
    console.log('🚨 CORS FIX: Redirecting getActiveTrades() to working RDS API with proper CORS');
    return this.getActiveTradesFromRDS();
  }

  async getTradeHistory(limit?: number): Promise<ApiResponse<any>> {
    const query = limit ? `?limit=${limit}` : '';
    return this.makeRequest('GET', `/trades/history${query}`);
  }

  async getTradeOverlays(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/trades/overlays');
  }

  // Strategy endpoints - LumiSignals RDS Data via Lambda
  async getStrategies(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/strategies');
  }

  async getStrategyDetails(strategyId: string): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', `/api/strategies/${strategyId}`);
  }

  async getStrategySignals(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/signals');
  }

  async getStrategyPerformance(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/performance');
  }

  async getActivePositions(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/positions');
  }

  async getPortfolioSummary(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/portfolio');
  }

  async getPairPerformance(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/pairs');
  }

  async getRiskExposure(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/exposure');
  }

  // Get active trades from RDS API
  async getActiveTradesFromRDS(): Promise<ApiResponse<any>> {
    console.log('🎯 FETCHING ACTIVE TRADES from RDS API...');
    const result = await this.makeRDSRequest('GET', '/active-trades');
    console.log('📊 Active trades API result:', {
      success: result.success,
      dataCount: result.data ? (Array.isArray(result.data) ? result.data.length : 'not array') : 'no data',
      error: result.error
    });
    return result;
  }

  // Get dashboard data (includes active trades)
  async getDashboardDataFromRDS(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/dashboard');
  }

  // Get positions data from RDS API
  async getPositionsFromRDS(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/positions');
  }

  // Get currency exposures from RDS API
  async getExposuresFromRDS(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/exposures');
  }

  // Get portfolio summary from RDS API
  async getPortfolioSummaryFromRDS(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/portfolio-summary');
  }

  // Get candlestick data directly from Redis (bypasses Lambda strategies) - FORCE UPDATE 2025-08-05
  async getCandlestickDataFromRDS(currencyPair: string, timeframe: string = 'H1', count: number = 50): Promise<ApiResponse<any>> {
    console.log(`⚠️ DEPRECATED: RDS API has no candlestick data. Redirecting to Direct Candlestick API for ${currencyPair} ${timeframe}`);
    
    // CORS FIX: RDS API returns empty data, redirect to working Direct Candlestick API
    return this.getCandlestickData(currencyPair, timeframe, count);
  }

  async getCandlestickData(currencyPair: string, timeframe: string = 'H1', count: number = 50): Promise<ApiResponse<any>> {
    console.log(`🚀 Direct Candlestick API call: ${currencyPair} ${timeframe} (${count} candles)`);
    
    try {
      // Use the working Direct Candlestick API with proper path format
      // Add timestamp to bypass any cached CORS responses
      const timestamp = Date.now();
      const directUrl = `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/${currencyPair}/${timeframe}?count=${count}&_t=${timestamp}`;
      
      const response = await fetch(directUrl, {
        method: 'GET',
        // No custom headers to ensure this is a "simple" CORS request
        // This avoids the OPTIONS preflight request entirely
        mode: 'cors', // Explicitly enable CORS
        credentials: 'omit', // Don't send credentials
        signal: AbortSignal.timeout(10000) // 10 second timeout to prevent hanging requests
      });
      
      if (!response.ok) {
        throw new Error(`Direct Candlestick API failed: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.success && data.data && data.data.length > 0) {
        console.log(`✅ Direct Candlestick API success for ${currencyPair}: ${data.data.length} candles`);
        return {
          success: data.success,
          data: data.data,
          timestamp: data.metadata?.timestamp || new Date().toISOString()
        };
      } else {
        console.log(`⚠️ Direct Candlestick API returned no data for ${currencyPair} (${data.data?.length || 0} candles)`);
        throw new Error(`No candlestick data available for ${currencyPair}`);
      }
    } catch (error) {
      console.error(`❌ Direct Candlestick API failed for ${currencyPair}:`, error);
      
      // Return detailed error with helpful debugging info
      return {
        success: false,
        data: [],
        error: `Candlestick API error for ${currencyPair}: ${error.message}. Check browser console for CORS/network issues.`,
        timestamp: new Date().toISOString()
      };
    }
  }

  // Get Redis status information
  async getRedisStatus(): Promise<ApiResponse<any>> {
    return this.makeRDSRequest('GET', '/redis-status');
  }

  // Fargate Data Orchestrator endpoints - REMOVED FOR SECURITY
  async getFargateHistoricalData(
    currencyPair: string, 
    timeframe: string = 'H1', 
    limit: number = 200
  ): Promise<ApiResponse<any>> {
    // SECURITY: Fargate access disabled from frontend
    return {
      success: false,
      data: {},
      error: 'Fargate access disabled for security',
      timestamp: new Date().toISOString(),
    };
  }

  async getFargateDataStatus(): Promise<ApiResponse<any>> {
    // SECURITY: Fargate access disabled from frontend
    return {
      success: false,
      data: {},
      error: 'Fargate access disabled for security',
      timestamp: new Date().toISOString(),
    };
  }

  async getAllCurrencyPairsData(timeframe: string = 'H1'): Promise<ApiResponse<any>> {
    const pairs = [
      'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD',
      'EUR_GBP', 'EUR_JPY', 'EUR_CAD', 'EUR_AUD', 'EUR_NZD', 'EUR_CHF',
      'GBP_JPY', 'GBP_CAD', 'GBP_AUD', 'GBP_NZD', 'GBP_CHF',
      'AUD_JPY', 'AUD_CAD', 'AUD_NZD', 'AUD_CHF',
      'NZD_JPY', 'NZD_CAD', 'NZD_CHF',
      'CAD_JPY', 'CAD_CHF',
      'CHF_JPY', 'USD_CHF'
    ];

    try {
      // SECURITY: Fargate access disabled - return empty data
      console.log('🔒 Security: getAllCurrencyPairsData disabled - Fargate access removed');
      const pairData = {};

      return {
        success: true,
        data: pairData,
        timestamp: new Date().toISOString(),
      };
    } catch (error: any) {
      return {
        success: false,
        data: {},
        error: error.message || 'Batch fetch failed',
        timestamp: new Date().toISOString(),
      };
    }
  }

  // Analytics endpoints
  async getMarketDataQuality(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=market-data-quality');
  }

  async getTradingActivity(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=trading-activity');
  }

  async getPerformanceAttribution(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=performance-attribution');
  }

  async getRiskMetrics(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=risk-metrics');
  }

  async getComplianceReport(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=compliance-report');
  }

  async getStrategyCorrelation(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/analytics?type=strategy-correlation');
  }

  // Real-time system health
  async getRealtimeHealth(): Promise<ApiResponse<any>> {
    return this.makeRequest('GET', '/system/realtime');
  }

  // Utility methods
  async testEndpoint(url: string): Promise<ApiResponse<any>> {
    try {
      const fullUrl = url.startsWith('http') ? url : `${this.client.defaults.baseURL}${url}`;
      const response = await axios.get(fullUrl, { timeout: 5000 });
      
      return {
        success: true,
        data: response.data,
        timestamp: new Date().toISOString(),
      };
    } catch (error: any) {
      return {
        success: false,
        data: {},
        error: error.message || 'Failed to test endpoint',
        timestamp: new Date().toISOString(),
      };
    }
  }

  // Batch requests for dashboard initialization
  async getDashboardData(): Promise<{
    health: ApiResponse<any>;
    marketData: ApiResponse<any>;
    momentum: ApiResponse<MomentumRanking>;
    portfolioOverview: ApiResponse<any>;
  }> {
    const [health, marketData, momentum, portfolioOverview] = await Promise.all([
      this.healthCheck(),
      this.getMarketData(),
      this.getMomentumRanking(),
      this.getPortfolioOverview(),
    ]);

    return {
      health,
      marketData,
      momentum,
      portfolioOverview,
    };
  }

  // Get all signal analytics for all currency pairs
  async getAllSignalAnalytics(): Promise<ApiResponse<Record<string, any>>> {
    try {
      console.log('🔍 Fetching all signal analytics from backend...');
      
      // Use Lambda Function URL for direct access - Lambda handles CORS
      const lambdaEndpoint = 'https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws/analytics/all-signals';
      
      try {
        const response = await fetch(lambdaEndpoint, {
          method: 'GET',
          mode: 'cors',
          credentials: 'omit'
        });
        
        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            console.log('✅ Successfully fetched signal analytics from Lambda');
            return {
              success: true,
              data: data.data,
              metadata: data.metadata
            };
          }
        }
        
        console.warn('⚠️ Lambda endpoint failed, falling back to mock data');
      } catch (error) {
        console.warn('⚠️ Failed to fetch from Lambda endpoint, using mock data:', error);
      }
      
      // Fallback to mock data if Lambda fails
      const mockData: Record<string, any> = {};
      const currencyPairs = [
        'EUR_USD', 'GBP_USD', 'USD_CAD', 'AUD_USD', 'USD_JPY', 'NZD_USD', 'USD_CHF',
        'EUR_GBP', 'EUR_JPY', 'GBP_JPY', 'AUD_JPY', 'EUR_CAD', 'GBP_CAD', 'AUD_CAD',
        'EUR_AUD', 'EUR_CHF', 'GBP_CHF', 'AUD_CHF', 'CAD_CHF', 'NZD_CHF', 'CHF_JPY',
        'NZD_JPY', 'CAD_JPY', 'EUR_NZD', 'GBP_NZD', 'AUD_NZD', 'NZD_CAD', 'GBP_AUD'
      ];

      currencyPairs.forEach(pair => {
        mockData[pair] = {
          fibonacci: {
            levels: [0.236, 0.382, 0.5, 0.618, 0.786],
            high: 1.1234,
            low: 1.0987,
            direction: 'bullish'
          },
          supplyDemand: {
            zones: [
              { type: 'supply', start: 1.1200, end: 1.1250, strength: 0.8 },
              { type: 'demand', start: 1.0950, end: 1.1000, strength: 0.9 }
            ]
          },
          momentum: {
            value: 0.65,
            direction: 'bullish',
            strength: 'strong'
          },
          trend: {
            direction: 'up',
            strength: 0.72,
            timeframes: {
              '5m': 'up',
              '15m': 'up',
              '1h': 'neutral',
              '4h': 'up'
            }
          },
          rsiSma: {
            rsi: 62,
            sma: 1.1100,
            quadrant: 'bullish'
          },
          adamButton: {
            sentiment: 'neutral',
            lastUpdate: new Date().toISOString()
          },
          scotiabank: {
            flow: 'buying',
            strength: 'moderate',
            volume: 250000000
          },
          candlestick: {
            patterns: [
              { name: 'hammer', timestamp: new Date().toISOString(), reliability: 0.75 }
            ]
          }
        };
      });

      // Simulate API call with actual endpoint when available
      // const response: AxiosResponse<any> = await this.client.get('/analytics/all-signals');
      
      return {
        success: true,
        data: mockData,
        timestamp: new Date().toISOString(),
      };
    } catch (error: any) {
      console.error('❌ Error fetching signal analytics:', error);
      return {
        success: false,
        data: {},
        error: error.message || 'Failed to fetch signal analytics',
        timestamp: new Date().toISOString(),
      };
    }
  }
}

// Create and export a singleton instance
export const api = new ApiService();

// Export types for use in components
export type { ApiResponse } from '../types/momentum';