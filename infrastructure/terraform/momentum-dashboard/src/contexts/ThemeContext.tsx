import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';

// Theme mode types
export type ThemeMode = 'light' | 'dark' | 'system';
export type EffectiveTheme = 'light' | 'dark';

// Theme context interface
interface ThemeContextType {
  mode: ThemeMode;
  effectiveTheme: EffectiveTheme;
  setMode: (mode: ThemeMode) => void;
  toggleTheme: () => void;
  isTransitioning: boolean;
}

// Create context
const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Theme detection script to prevent flash
export const themeInitScript = `
  (function() {
    function getTheme() {
      const stored = localStorage.getItem('lumitrade-theme');
      if (stored === 'light' || stored === 'dark') return stored;
      if (stored === 'system' || !stored) {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      }
      return 'dark'; // Default to dark for trading aesthetic
    }
    
    const theme = getTheme();
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.documentElement.style.colorScheme = theme;
  })();
`;

// Theme Provider Component
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>('system');
  const [effectiveTheme, setEffectiveTheme] = useState<EffectiveTheme>('dark');
  const [isTransitioning, setIsTransitioning] = useState(false);

  // Get effective theme based on mode and system preference
  const getEffectiveTheme = useCallback((themeMode: ThemeMode): EffectiveTheme => {
    if (themeMode === 'light' || themeMode === 'dark') {
      return themeMode;
    }
    
    // For 'system' mode, check system preference
    if (typeof window !== 'undefined') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    
    return 'dark'; // Default
  }, []);

  // Set theme mode with transition handling
  const setMode = useCallback((newMode: ThemeMode) => {
    setIsTransitioning(true);
    setModeState(newMode);
    
    const newEffectiveTheme = getEffectiveTheme(newMode);
    setEffectiveTheme(newEffectiveTheme);
    
    // Update DOM
    document.documentElement.classList.toggle('dark', newEffectiveTheme === 'dark');
    document.documentElement.style.colorScheme = newEffectiveTheme;
    
    // Persist preference
    localStorage.setItem('lumitrade-theme', newMode);
    
    // End transition
    setTimeout(() => setIsTransitioning(false), 300);
  }, [getEffectiveTheme]);

  // Toggle between light and dark (skip system)
  const toggleTheme = useCallback(() => {
    const newMode = effectiveTheme === 'dark' ? 'light' : 'dark';
    setMode(newMode);
  }, [effectiveTheme, setMode]);

  // Initialize theme on mount
  useEffect(() => {
    // Get stored preference
    const stored = localStorage.getItem('lumitrade-theme') as ThemeMode | null;
    const initialMode = stored || 'system';
    
    setModeState(initialMode);
    setEffectiveTheme(getEffectiveTheme(initialMode));
    
    // Add transition prevention class during initial load
    document.body.classList.add('theme-transitioning');
    requestAnimationFrame(() => {
      document.body.classList.remove('theme-transitioning');
    });
  }, [getEffectiveTheme]);

  // Listen for system theme changes
  useEffect(() => {
    if (mode !== 'system') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    
    const handleChange = (e: MediaQueryListEvent) => {
      setEffectiveTheme(e.matches ? 'dark' : 'light');
      document.documentElement.classList.toggle('dark', e.matches);
      document.documentElement.style.colorScheme = e.matches ? 'dark' : 'light';
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [mode]);

  // Keyboard shortcut for theme toggle (Ctrl/Cmd + Shift + T)
  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        toggleTheme();
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [toggleTheme]);

  return (
    <ThemeContext.Provider value={{
      mode,
      effectiveTheme,
      setMode,
      toggleTheme,
      isTransitioning
    }}>
      {children}
    </ThemeContext.Provider>
  );
}

// Hook to use theme
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

// Utility to get theme-aware class names
export function getThemeClass(lightClass: string, darkClass: string) {
  return `${lightClass} dark:${darkClass}`;
}