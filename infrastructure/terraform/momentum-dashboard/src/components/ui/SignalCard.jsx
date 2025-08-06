import React from 'react';

const SignalCard = ({ direction, strategy, entry, sl, tp, rr, confidence }) => {
  const getDirectionColor = (dir) => {
    return dir === 'BUY' 
      ? 'text-green-600 dark:text-green-400' 
      : 'text-red-600 dark:text-red-400';
  };

  const getConfidenceColor = (conf) => {
    if (conf >= 80) return 'text-green-600 dark:text-green-400';
    if (conf >= 60) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-gray-600 dark:text-gray-400';
  };

  const getRRColor = (rrValue) => {
    if (rrValue >= 3.0) return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
    if (rrValue >= 2.0) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
    return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
  };

  return (
    <div className="
      bg-white dark:bg-gray-800 
      rounded-lg border border-gray-200 dark:border-gray-700
      p-4 shadow-sm
      transition-colors duration-200
    ">
      {/* Direction */}
      <div className={`text-lg font-bold mb-2 ${getDirectionColor(direction)}`}>
        {direction}
      </div>

      {/* Strategy Name */}
      <div className="text-sm font-medium text-gray-900 dark:text-white mb-2">
        {strategy}
      </div>

      {/* Trade Levels */}
      <div className="text-xs text-gray-600 dark:text-gray-400 mb-3">
        Entry: {entry} • SL: {sl} • TP: {tp}
      </div>

      {/* R:R and Confidence */}
      <div className="flex justify-between items-center">
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getRRColor(rr)}`}>
          R:R {rr}
        </span>
        <div className={`text-xs font-medium ${getConfidenceColor(confidence)}`}>
          {confidence}% confidence
        </div>
      </div>
    </div>
  );
};

export default SignalCard;