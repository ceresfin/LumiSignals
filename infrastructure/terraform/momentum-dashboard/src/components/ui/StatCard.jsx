import React from 'react';

const StatCard = ({ label, value, className = '' }) => {
  return (
    <div className={`
      bg-white dark:bg-gray-800 
      rounded-lg shadow-sm border border-gray-200 dark:border-gray-700
      p-4 
      transition-colors duration-200
      ${className}
    `}>
      <div className="text-2xl font-bold text-gray-900 dark:text-white mb-1">
        {value}
      </div>
      <div className="text-sm text-gray-600 dark:text-gray-400">
        {label}
      </div>
    </div>
  );
};

export default StatCard;