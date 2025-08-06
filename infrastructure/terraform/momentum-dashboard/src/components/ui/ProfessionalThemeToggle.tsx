import React, { useState, useEffect } from 'react';
import { Sun, Moon, Monitor, ChevronDown } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface ThemeOption {
  id: 'light' | 'dark' | 'system';
  label: string;
  icon: React.ReactNode;
  description: string;
}

interface ProfessionalThemeToggleProps {
  variant?: 'minimal' | 'detailed' | 'dropdown';
  position?: 'header' | 'sidebar' | 'floating';
  showLabels?: boolean;
  className?: string;
}

export const ProfessionalThemeToggle: React.FC<ProfessionalThemeToggleProps> = ({
  variant = 'detailed',
  position = 'header',
  showLabels = true,
  className = ''
}) => {
  const { mode, setMode, effectiveTheme } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Prevent hydration issues
  useEffect(() => {
    setMounted(true);
  }, []);

  const themeOptions: ThemeOption[] = [
    {
      id: 'light',
      label: 'Light',
      icon: <Sun className="w-4 h-4" />,
      description: 'Optimized for daylight analysis'
    },
    {
      id: 'dark',
      label: 'Dark',
      icon: <Moon className="w-4 h-4" />,
      description: 'Perfect for 24/7 trading'
    },
    {
      id: 'system',
      label: 'System',
      icon: <Monitor className="w-4 h-4" />,
      description: 'Follow system preference'
    }
  ];

  const getCurrentThemeInfo = () => {
    const current = themeOptions.find(option => option.id === mode);
    return current || themeOptions[0];
  };

  if (!mounted) {
    return (
      <div className="w-32 h-10 bg-gray-200 dark:bg-gray-700 rounded-lg animate-pulse" />
    );
  }

  // Minimal variant - simple toggle
  if (variant === 'minimal') {
    return (
      <button
        onClick={() => setMode(effectiveTheme === 'dark' ? 'light' : 'dark')}
        className={`
          relative p-2 rounded-lg transition-all duration-300 
          bg-gray-100 dark:bg-gray-800 
          hover:bg-gray-200 dark:hover:bg-gray-700
          border border-gray-200 dark:border-gray-600
          hover:border-gray-300 dark:hover:border-gray-500
          focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
          ${className}
        `}
        aria-label={`Switch to ${effectiveTheme === 'dark' ? 'light' : 'dark'} mode`}
      >
        <div className="relative w-5 h-5">
          <Sun className={`absolute inset-0 w-5 h-5 text-amber-500 transition-all duration-300 ${
            effectiveTheme === 'dark' ? 'opacity-0 rotate-90 scale-0' : 'opacity-100 rotate-0 scale-100'
          }`} />
          <Moon className={`absolute inset-0 w-5 h-5 text-blue-400 transition-all duration-300 ${
            effectiveTheme === 'dark' ? 'opacity-100 rotate-0 scale-100' : 'opacity-0 -rotate-90 scale-0'
          }`} />
        </div>
      </button>
    );
  }

  // Dropdown variant
  if (variant === 'dropdown') {
    const currentTheme = getCurrentThemeInfo();
    
    return (
      <div className={`relative ${className}`}>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`
            flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-200
            bg-gray-100 dark:bg-gray-800 
            hover:bg-gray-200 dark:hover:bg-gray-700
            border border-gray-200 dark:border-gray-600
            hover:border-gray-300 dark:hover:border-gray-500
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
            text-sm font-medium text-gray-700 dark:text-gray-300
          `}
        >
          {currentTheme.icon}
          {showLabels && <span>{currentTheme.label}</span>}
          <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${
            isOpen ? 'rotate-180' : ''
          }`} />
        </button>

        {isOpen && (
          <>
            <div 
              className="fixed inset-0 z-10" 
              onClick={() => setIsOpen(false)}
            />
            <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-600 z-20">
              <div className="p-1">
                {themeOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => {
                      setMode(option.id);
                      setIsOpen(false);
                    }}
                    className={`
                      w-full flex items-start gap-3 px-3 py-2 rounded-md transition-all duration-200 text-left
                      ${mode === option.id 
                        ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' 
                        : 'hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300'
                      }
                    `}
                  >
                    <div className="mt-0.5">{option.icon}</div>
                    <div className="flex-1">
                      <div className="font-medium">{option.label}</div>
                      <div className="text-xs opacity-75">{option.description}</div>
                    </div>
                    {mode === option.id && (
                      <div className="w-2 h-2 bg-blue-500 rounded-full mt-2" />
                    )}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    );
  }

  // Detailed variant - segmented control
  return (
    <div className={`
      flex items-center gap-0.5 p-1 rounded-lg transition-all duration-300
      bg-gray-100 dark:bg-gray-800 
      border border-gray-200 dark:border-gray-600
      ${className}
    `}>
      {themeOptions.map((option) => (
        <button
          key={option.id}
          onClick={() => setMode(option.id)}
          className={`
            relative flex items-center gap-2 px-3 py-2 rounded-md transition-all duration-200
            text-sm font-medium
            ${mode === option.id 
              ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' 
              : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-gray-700'
            }
          `}
          aria-pressed={mode === option.id}
          title={option.description}
        >
          <div className="relative">
            {option.icon}
            {mode === option.id && (
              <div className="absolute -inset-1 rounded-md border-2 border-blue-500 opacity-20 animate-pulse" />
            )}
          </div>
          {showLabels && <span>{option.label}</span>}
        </button>
      ))}
      
      {/* Status indicator */}
      <div className="ml-2 flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 dark:bg-gray-700">
        <div className={`w-2 h-2 rounded-full ${
          effectiveTheme === 'dark' ? 'bg-blue-400' : 'bg-amber-400'
        }`} />
        <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">
          {effectiveTheme === 'dark' ? 'Dark' : 'Light'}
        </span>
      </div>
    </div>
  );
};

// Hook for theme-aware styling
export const useThemeStyles = () => {
  const { effectiveTheme } = useTheme();
  
  return {
    isDark: effectiveTheme === 'dark',
    theme: {
      background: effectiveTheme === 'dark' ? '#1E1E1E' : '#FFFFFF',
      surface: effectiveTheme === 'dark' ? '#2C2C2C' : '#F9F9F9',
      text: effectiveTheme === 'dark' ? '#F1F1F1' : '#1D1E1F',
      textSecondary: effectiveTheme === 'dark' ? '#B3B3B3' : '#6B7280',
      border: effectiveTheme === 'dark' ? '#3B3B3B' : '#E5E5E5',
      accent: effectiveTheme === 'dark' ? '#A2C4BA' : '#8A9C91',
      positive: effectiveTheme === 'dark' ? '#A2C4BA' : '#8A9C91',
      negative: effectiveTheme === 'dark' ? '#D9AAB1' : '#B4837D',
      neutral: '#C2A565'
    }
  };
};