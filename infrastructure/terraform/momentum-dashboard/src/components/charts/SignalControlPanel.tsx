import React from 'react';
import { X, RefreshCw } from 'lucide-react';

export interface SignalToggle {
  id: string;
  label: string;
  enabled: boolean;
  group: 'priceAction' | 'sentiment' | 'structure';
}

interface SignalGroup {
  title: string;
  toggles: SignalToggle[];
  colorClass: string;
  bgClass: string;
}

interface SignalControlPanelProps {
  signals: SignalToggle[];
  onToggleSignal: (id: string) => void;
  onClearAll: () => void;
  onRefreshSignals: () => void;
  isRefreshing?: boolean;
}

export const SignalControlPanel: React.FC<SignalControlPanelProps> = ({
  signals,
  onToggleSignal,
  onClearAll,
  onRefreshSignals,
  isRefreshing = false,
}) => {
  const hasActiveSignals = signals.some(s => s.enabled);

  // Group signals by category with proper styling
  const priceActionSignals = signals.filter(s => s.group === 'priceAction');
  const sentimentSignals = signals.filter(s => s.group === 'sentiment');
  const structureSignals = signals.filter(s => s.group === 'structure');

  return (
    <div className="w-full bg-gray-900/50 dark:bg-gray-900/50 backdrop-blur-sm rounded-lg p-4 mb-4 border border-gray-700/50">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">Signal Control</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={onRefreshSignals}
            disabled={isRefreshing || !hasActiveSignals}
            className={`text-xs px-3 py-1 rounded-md flex items-center gap-1 transition-all ${
              isRefreshing || !hasActiveSignals
                ? 'bg-gray-800/50 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 text-white'
            }`}
          >
            <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Signals'}
          </button>
          {hasActiveSignals && (
            <button
              onClick={onClearAll}
              className="text-xs px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1"
            >
              <X className="w-3 h-3" />
              Clear All
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Price Action Group */}
        <div className="rounded-lg p-3 bg-lumitrade-soft-eucalyptus/5 border border-lumitrade-soft-eucalyptus/20">
          <h4 className="text-xs font-semibold mb-2 text-lumitrade-sage">Price Action</h4>
          <div className="space-y-2">
            {priceActionSignals.map((toggle) => (
              <label key={toggle.id} className="flex items-center gap-2 cursor-pointer group">
                <div className="relative">
                  <input
                    type="checkbox"
                    className="sr-only peer"
                    checked={toggle.enabled}
                    onChange={() => onToggleSignal(toggle.id)}
                  />
                  <div className="w-9 h-5 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-lumitrade-sage"></div>
                </div>
                <span className="text-xs text-gray-400 group-hover:text-gray-200 transition-colors select-none">
                  {toggle.label}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* Sentiment Group */}
        <div className="rounded-lg p-3 bg-lumitrade-rose/5 border border-lumitrade-rose/20">
          <h4 className="text-xs font-semibold mb-2 text-lumitrade-dusty-rose">Sentiment</h4>
          <div className="space-y-2">
            {sentimentSignals.map((toggle) => (
              <label key={toggle.id} className="flex items-center gap-2 cursor-pointer group">
                <div className="relative">
                  <input
                    type="checkbox"
                    className="sr-only peer"
                    checked={toggle.enabled}
                    onChange={() => onToggleSignal(toggle.id)}
                  />
                  <div className="w-9 h-5 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-lumitrade-dusty-rose"></div>
                </div>
                <span className="text-xs text-gray-400 group-hover:text-gray-200 transition-colors select-none">
                  {toggle.label}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* Structure Group */}
        <div className="rounded-lg p-3 bg-lumitrade-gold/5 border border-lumitrade-gold/20">
          <h4 className="text-xs font-semibold mb-2 text-lumitrade-gold">Structure</h4>
          <div className="space-y-2">
            {structureSignals.map((toggle) => (
              <label key={toggle.id} className="flex items-center gap-2 cursor-pointer group">
                <div className="relative">
                  <input
                    type="checkbox"
                    className="sr-only peer"
                    checked={toggle.enabled}
                    onChange={() => onToggleSignal(toggle.id)}
                  />
                  <div className="w-9 h-5 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-lumitrade-gold"></div>
                </div>
                <span className="text-xs text-gray-400 group-hover:text-gray-200 transition-colors select-none">
                  {toggle.label}
                </span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};