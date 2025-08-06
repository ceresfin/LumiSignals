import React from 'react';

const StrategyCard = ({ name, curve, timeframe, pnl, winRate, positions, rr, trades }) => {
  const getRRColor = (rrValue) => {
    if (rrValue >= 3.0) return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
    if (rrValue >= 2.0) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
    return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
  };

  const getPnLColor = (pnlValue) => {
    return pnlValue >= 0 
      ? 'text-green-600 dark:text-green-400' 
      : 'text-red-600 dark:text-red-400';
  };

  return (
    <div className="
      bg-white dark:bg-gray-800 
      rounded-lg border border-gray-200 dark:border-gray-700
      p-4 shadow-sm
      transition-colors duration-200
      hover:shadow-md
    ">
      {/* Title Row */}
      <div className="flex justify-between items-start mb-3">
        <div className="text-sm text-gray-600 dark:text-gray-400">
          {curve} • {timeframe}
        </div>
        <div className="text-sm font-medium text-gray-900 dark:text-white text-right">
          {name}
        </div>
      </div>

      {/* P&L and R:R Row */}
      <div className="flex justify-between items-center mb-3">
        <div className={`text-lg font-bold ${getPnLColor(pnl)}`}>
          {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
        </div>
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getRRColor(rr)}`}>
          R:R {rr}
        </span>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-2 text-xs text-gray-600 dark:text-gray-400">
        <div>
          <span className="font-medium">{trades}</span> trades
        </div>
        <div>
          <span className="font-medium">{positions}</span> positions
        </div>
        <div>
          <span className="font-medium">{(winRate * 100).toFixed(0)}%</span> win
        </div>
      </div>
    </div>
  );
};

export default StrategyCard;