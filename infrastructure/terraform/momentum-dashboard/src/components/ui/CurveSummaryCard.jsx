import React from 'react';

const CurveSummaryCard = ({ curveName, strategyCount, totalPnl }) => {
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
    ">
      {/* Curve Name */}
      <div className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
        {curveName}
      </div>

      {/* Strategy Count */}
      <div className="text-sm text-gray-600 dark:text-gray-400 mb-3">
        {strategyCount} {strategyCount === 1 ? 'Strategy' : 'Strategies'}
      </div>

      {/* Total P&L */}
      <div className={`text-xl font-bold ${getPnLColor(totalPnl)}`}>
        {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
      </div>
    </div>
  );
};

export default CurveSummaryCard;