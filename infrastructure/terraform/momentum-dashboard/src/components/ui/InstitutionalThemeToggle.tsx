import React from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import { Sun, Moon, Monitor } from 'lucide-react';

export const InstitutionalThemeToggle: React.FC = () => {
  const { mode, effectiveTheme, setMode, isTransitioning } = useTheme();

  const options = [
    { value: 'light' as const, icon: Sun, label: 'Light' },
    { value: 'dark' as const, icon: Moon, label: 'Dark' },
    { value: 'system' as const, icon: Monitor, label: 'System' }
  ];

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-0.5">
        {options.map((option) => {
          const Icon = option.icon;
          const isActive = mode === option.value;
          
          return (
            <button
              key={option.value}
              onClick={() => setMode(option.value)}
              disabled={isTransitioning}
              className={`
                relative flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium
                transition-all duration-200 ${isTransitioning ? 'cursor-wait' : ''}
                ${isActive 
                  ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' 
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                }
              `}
              aria-label={`Switch to ${option.label} theme`}
              aria-pressed={isActive}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden sm:inline">{option.label}</span>
            </button>
          );
        })}
      </div>
      
      {/* Debug info */}
      <div className="text-xs text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800 px-2 py-1 rounded border">
        Mode: {mode} | Effective: {effectiveTheme} | HTML has dark: {document.documentElement.classList.contains('dark') ? 'Yes' : 'No'}
      </div>
    </div>
  );
};

// Simplified toggle for mobile/compact views
export const CompactThemeToggle: React.FC = () => {
  const { effectiveTheme, toggleTheme, isTransitioning } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      disabled={isTransitioning}
      className={`
        p-2 rounded-lg border border-border-light dark:border-border-dark
        bg-surface-light dark:bg-surface-dark
        hover:bg-elevated-light dark:hover:bg-elevated-dark
        transition-all duration-200
        ${isTransitioning ? 'cursor-wait opacity-50' : ''}
      `}
      aria-label={`Switch to ${effectiveTheme === 'dark' ? 'light' : 'dark'} theme`}
    >
      {effectiveTheme === 'dark' ? (
        <Sun className="w-5 h-5 text-pipstop-accent" />
      ) : (
        <Moon className="w-5 h-5 text-pipstop-primary" />
      )}
    </button>
  );
};