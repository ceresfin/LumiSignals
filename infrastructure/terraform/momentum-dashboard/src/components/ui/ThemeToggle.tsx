import React from 'react';
import { Sun, Moon } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';

interface ThemeToggleProps {
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ 
  className = '', 
  size = 'md' 
}) => {
  const [theme, setTheme] = useTheme();

  const getSizeClasses = () => {
    switch (size) {
      case 'sm':
        return 'w-8 h-8';
      case 'md':
        return 'w-10 h-10';
      case 'lg':
        return 'w-12 h-12';
      default:
        return 'w-10 h-10';
    }
  };

  const getIconSize = () => {
    switch (size) {
      case 'sm':
        return 'w-4 h-4';
      case 'md':
        return 'w-5 h-5';
      case 'lg':
        return 'w-6 h-6';
      default:
        return 'w-5 h-5';
    }
  };

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  return (
    <button
      onClick={toggleTheme}
      className={`
        ${getSizeClasses()}
        flex items-center justify-center
        bg-surface-light dark:bg-surface-dark
        hover:bg-elevated-light dark:hover:bg-elevated-dark
        border border-border-light dark:border-border-dark
        rounded-lg
        transition-all duration-200
        text-text-primary-light dark:text-text-primary-dark
        hover:text-pipstop-primary
        focus:outline-none
        focus:ring-2 focus:ring-pipstop-primary/50
        ${className}
      `}
      title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
    >
      {theme === 'light' ? (
        <Moon className={`${getIconSize()} transition-transform duration-200`} />
      ) : (
        <Sun className={`${getIconSize()} transition-transform duration-200`} />
      )}
    </button>
  );
};

export default ThemeToggle;