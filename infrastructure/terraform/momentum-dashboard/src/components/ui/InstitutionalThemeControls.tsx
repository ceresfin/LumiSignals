import React, { useState, useEffect, useRef } from 'react';
import { Sun, Moon, Monitor, Settings, Check, Clock, Eye, Palette } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface InstitutionalThemeControlsProps {
  placement: 'header' | 'sidebar' | 'settings' | 'floating';
  priority: 'primary' | 'secondary' | 'tertiary';
  showSystemStatus?: boolean;
  showTransitionFeedback?: boolean;
  compactMode?: boolean;
  className?: string;
}

// Professional status indicator for system state
const SystemStatusIndicator = ({ 
  theme, 
  systemPreference, 
  isTransitioning 
}: { 
  theme: any; 
  systemPreference: 'light' | 'dark';
  isTransitioning: boolean;
}) => {
  return (
    <div className="flex items-center gap-2 text-xs" style={{ color: theme.textSecondary }}>
      <Monitor className="w-3 h-3" />
      <span>System:</span>
      <span className="font-medium capitalize">{systemPreference}</span>
      {isTransitioning && (
        <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
      )}
    </div>
  );
};

// Accessibility-first keyboard navigation
const useKeyboardNavigation = (
  isOpen: boolean,
  setIsOpen: (open: boolean) => void,
  optionsRef: React.RefObject<HTMLDivElement>
) => {
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
      
      if (e.key === 'Tab') {
        const focusableElements = optionsRef.current?.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        
        if (focusableElements && focusableElements.length > 0) {
          const firstElement = focusableElements[0] as HTMLElement;
          const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;
          
          if (e.shiftKey && document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
          } else if (!e.shiftKey && document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, setIsOpen, optionsRef]);
};

// Theme preference with usage context
const ThemePreference = ({ 
  id, 
  label, 
  description, 
  usageContext, 
  icon, 
  isSelected, 
  isEffective,
  onClick,
  theme
}: {
  id: string;
  label: string;
  description: string;
  usageContext: string;
  icon: React.ReactNode;
  isSelected: boolean;
  isEffective: boolean;
  onClick: () => void;
  theme: any;
}) => {
  return (
    <button
      onClick={onClick}
      className={`
        w-full flex items-start gap-3 p-3 rounded-lg transition-all duration-200 text-left
        hover:bg-gray-50 dark:hover:bg-gray-700/50
        focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
        ${isSelected ? 'bg-blue-50 dark:bg-blue-900/20 ring-1 ring-blue-200 dark:ring-blue-800' : ''}
      `}
      role="option"
      aria-selected={isSelected}
      aria-describedby={`${id}-description`}
    >
      <div className="flex-shrink-0 mt-0.5">
        <div className={`p-2 rounded-md ${
          isSelected 
            ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' 
            : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
        }`}>
          {icon}
        </div>
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`font-medium ${
            isSelected ? 'text-blue-700 dark:text-blue-300' : 'text-gray-900 dark:text-gray-100'
          }`}>
            {label}
          </span>
          {isEffective && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30">
              <div className="w-2 h-2 bg-green-500 rounded-full" />
              <span className="text-xs font-medium text-green-700 dark:text-green-300">
                Active
              </span>
            </div>
          )}
        </div>
        
        <div className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {description}
        </div>
        
        <div className="mt-2 text-xs" style={{ color: theme.textMuted }}>
          <span className="font-medium">Best for:</span> {usageContext}
        </div>
      </div>
      
      {isSelected && (
        <div className="flex-shrink-0 mt-2">
          <Check className="w-4 h-4 text-blue-600 dark:text-blue-400" />
        </div>
      )}
    </button>
  );
};

// Professional transition feedback
const TransitionFeedback = ({ 
  isTransitioning, 
  newTheme, 
  theme 
}: { 
  isTransitioning: boolean;
  newTheme: string;
  theme: any;
}) => {
  if (!isTransitioning) return null;

  return (
    <div 
      className="fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-2 rounded-lg shadow-lg border backdrop-blur-sm"
      style={{
        backgroundColor: theme.background,
        borderColor: theme.border,
        color: theme.text
      }}
    >
      <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
      <span className="text-sm font-medium">
        Switching to {newTheme} mode...
      </span>
    </div>
  );
};

export const InstitutionalThemeControls: React.FC<InstitutionalThemeControlsProps> = ({
  placement,
  priority,
  showSystemStatus = true,
  showTransitionFeedback = true,
  compactMode = false,
  className = ''
}) => {
  const { mode, effectiveTheme, setMode, isTransitioning } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const [systemPreference, setSystemPreference] = useState<'light' | 'dark'>('dark');
  const [lastUsedMode, setLastUsedMode] = useState<string>('');
  const optionsRef = useRef<HTMLDivElement>(null);

  // Detect system preference
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      setSystemPreference(mediaQuery.matches ? 'dark' : 'light');
      
      const handleChange = (e: MediaQueryListEvent) => {
        setSystemPreference(e.matches ? 'dark' : 'light');
      };
      
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }
  }, []);

  // Theme definitions with professional context
  const themeOptions = [
    {
      id: 'light' as const,
      label: 'Light Mode',
      description: 'Optimized for daylight analysis and bright environments',
      usageContext: 'Market analysis, documentation, daytime trading',
      icon: <Sun className="w-4 h-4" />,
      isEffective: effectiveTheme === 'light'
    },
    {
      id: 'dark' as const,
      label: 'Dark Mode',
      description: 'Designed for extended trading sessions and low-light conditions',
      usageContext: '24/7 trading, night sessions, reduced eye strain',
      icon: <Moon className="w-4 h-4" />,
      isEffective: effectiveTheme === 'dark'
    },
    {
      id: 'system' as const,
      label: 'System Preference',
      description: 'Automatically follows your operating system theme setting',
      usageContext: 'Seamless integration with system workflow',
      icon: <Monitor className="w-4 h-4" />,
      isEffective: mode === 'system'
    }
  ];

  const theme = {
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      text: '#1f2937',
      textSecondary: '#6b7280',
      textMuted: '#9ca3af',
      border: '#e5e7eb'
    },
    dark: {
      background: '#1e1e1e',
      surface: '#2c2c2c',
      text: '#f1f1f1',
      textSecondary: '#b3b3b3',
      textMuted: '#8a8a8a',
      border: '#3b3b3b'
    }
  }[effectiveTheme];

  useKeyboardNavigation(isOpen, setIsOpen, optionsRef);

  const handleThemeChange = (newMode: 'light' | 'dark' | 'system') => {
    setLastUsedMode(effectiveTheme);
    setMode(newMode);
    setIsOpen(false);
    
    // Analytics for institutional usage patterns
    if (typeof window !== 'undefined' && (window as any).analytics) {
      (window as any).analytics.track('Theme Changed', {
        from: mode,
        to: newMode,
        placement,
        timestamp: new Date().toISOString()
      });
    }
  };

  // Compact mode for secondary placements
  if (compactMode) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <button
          onClick={() => handleThemeChange(effectiveTheme === 'dark' ? 'light' : 'dark')}
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          style={{ color: theme.textSecondary }}
          title={`Switch to ${effectiveTheme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label={`Switch to ${effectiveTheme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {effectiveTheme === 'dark' ? 
            <Sun className="w-4 h-4" /> : 
            <Moon className="w-4 h-4" />
          }
        </button>
        {showSystemStatus && (
          <SystemStatusIndicator 
            theme={theme}
            systemPreference={systemPreference}
            isTransitioning={isTransitioning}
          />
        )}
      </div>
    );
  }

  // Primary theme control for main placements
  return (
    <div className={`relative ${className}`}>
      {/* Main Control Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`
          flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-200
          ${priority === 'primary' ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}
          border border-gray-200 dark:border-gray-600
          hover:border-gray-300 dark:hover:border-gray-500
          focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
          text-sm font-medium
        `}
        style={{ color: theme.text }}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label="Theme preferences"
      >
        <Palette className="w-4 h-4" />
        {placement !== 'floating' && (
          <>
            <span>Theme</span>
            <div className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-full ${
                effectiveTheme === 'dark' ? 'bg-blue-400' : 'bg-amber-400'
              }`} />
              <span className="text-xs capitalize" style={{ color: theme.textSecondary }}>
                {effectiveTheme}
              </span>
            </div>
          </>
        )}
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <>
          <div 
            className="fixed inset-0 z-20" 
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
          
          <div 
            ref={optionsRef}
            className="absolute right-0 mt-2 w-80 rounded-lg shadow-lg border z-30"
            style={{
              backgroundColor: theme.background,
              borderColor: theme.border
            }}
            role="menu"
            aria-orientation="vertical"
            aria-labelledby="theme-menu"
          >
            <div className="p-3">
              {/* Header */}
              <div className="flex items-center gap-2 mb-4 pb-3 border-b" style={{ borderColor: theme.border }}>
                <Settings className="w-4 h-4" style={{ color: theme.textSecondary }} />
                <h3 className="text-sm font-semibold" style={{ color: theme.text }}>
                  Theme Preferences
                </h3>
              </div>

              {/* System Status */}
              {showSystemStatus && (
                <div className="mb-4 p-2 rounded-lg bg-gray-50 dark:bg-gray-800/50">
                  <SystemStatusIndicator 
                    theme={theme}
                    systemPreference={systemPreference}
                    isTransitioning={isTransitioning}
                  />
                </div>
              )}

              {/* Theme Options */}
              <div className="space-y-2" role="group" aria-label="Theme options">
                {themeOptions.map((option) => (
                  <ThemePreference
                    key={option.id}
                    id={option.id}
                    label={option.label}
                    description={option.description}
                    usageContext={option.usageContext}
                    icon={option.icon}
                    isSelected={mode === option.id}
                    isEffective={option.isEffective}
                    onClick={() => handleThemeChange(option.id)}
                    theme={theme}
                  />
                ))}
              </div>

              {/* Usage Tips */}
              <div className="mt-4 pt-3 border-t" style={{ borderColor: theme.border }}>
                <div className="flex items-start gap-2">
                  <Eye className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: theme.textSecondary }} />
                  <div className="text-xs" style={{ color: theme.textMuted }}>
                    <strong>Pro tip:</strong> Use Cmd/Ctrl + Shift + T to quickly toggle between light and dark modes
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Transition Feedback */}
      {showTransitionFeedback && (
        <TransitionFeedback 
          isTransitioning={isTransitioning}
          newTheme={effectiveTheme}
          theme={theme}
        />
      )}
    </div>
  );
};

// Hook for global keyboard shortcuts
export const useThemeKeyboardShortcuts = () => {
  const { toggleTheme } = useTheme();
  
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        toggleTheme();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [toggleTheme]);
};

// Usage examples for different placements
export const ThemeControlExamples = {
  // Header placement - primary navigation
  Header: () => (
    <InstitutionalThemeControls 
      placement="header" 
      priority="primary"
      showSystemStatus={true}
      className="ml-4"
    />
  ),
  
  // Sidebar placement - secondary access
  Sidebar: () => (
    <InstitutionalThemeControls 
      placement="sidebar" 
      priority="secondary"
      compactMode={true}
      showSystemStatus={false}
      className="mb-4"
    />
  ),
  
  // Settings page - detailed control
  Settings: () => (
    <InstitutionalThemeControls 
      placement="settings" 
      priority="primary"
      showSystemStatus={true}
      showTransitionFeedback={true}
      className="w-full"
    />
  ),
  
  // Floating action - quick access
  Floating: () => (
    <InstitutionalThemeControls 
      placement="floating" 
      priority="tertiary"
      compactMode={true}
      showSystemStatus={false}
      className="fixed bottom-4 right-4 z-40"
    />
  )
};