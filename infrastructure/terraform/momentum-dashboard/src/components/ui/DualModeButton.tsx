import React from 'react';
import { useTheme } from '../../contexts/ThemeContext';

interface DualModeButtonProps {
  variant: 'primary' | 'secondary' | 'danger' | 'success';
  size: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  loading?: boolean;
  icon?: React.ReactNode;
}

export const DualModeButton: React.FC<DualModeButtonProps> = ({
  variant,
  size,
  children,
  onClick,
  disabled = false,
  loading = false,
  icon
}) => {
  const { effectiveTheme } = useTheme();

  // Theme-aware button styles
  const buttonStyles = {
    light: {
      primary: {
        base: 'bg-gradient-to-r from-blue-600 to-blue-700 text-white border border-blue-600 shadow-sm',
        hover: 'hover:from-blue-700 hover:to-blue-800 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-blue-800 active:to-blue-900 active:translate-y-0',
        disabled: 'disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed'
      },
      secondary: {
        base: 'bg-white text-gray-700 border border-gray-300 shadow-sm',
        hover: 'hover:bg-gray-50 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:bg-gray-100 active:translate-y-0',
        disabled: 'disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed'
      },
      danger: {
        base: 'bg-gradient-to-r from-red-600 to-red-700 text-white border border-red-600 shadow-sm',
        hover: 'hover:from-red-700 hover:to-red-800 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-red-800 active:to-red-900 active:translate-y-0',
        disabled: 'disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed'
      },
      success: {
        base: 'bg-gradient-to-r from-green-600 to-green-700 text-white border border-green-600 shadow-sm',
        hover: 'hover:from-green-700 hover:to-green-800 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-green-800 active:to-green-900 active:translate-y-0',
        disabled: 'disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed'
      }
    },
    dark: {
      primary: {
        base: 'bg-gradient-to-r from-blue-500 to-blue-600 text-gray-900 border border-blue-500 shadow-sm',
        hover: 'hover:from-blue-400 hover:to-blue-500 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-blue-600 active:to-blue-700 active:translate-y-0',
        disabled: 'disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed'
      },
      secondary: {
        base: 'bg-gray-700 text-gray-200 border border-gray-600 shadow-sm',
        hover: 'hover:bg-gray-600 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:bg-gray-800 active:translate-y-0',
        disabled: 'disabled:bg-gray-800 disabled:text-gray-500 disabled:cursor-not-allowed'
      },
      danger: {
        base: 'bg-gradient-to-r from-red-500 to-red-600 text-white border border-red-500 shadow-sm',
        hover: 'hover:from-red-400 hover:to-red-500 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-red-600 active:to-red-700 active:translate-y-0',
        disabled: 'disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed'
      },
      success: {
        base: 'bg-gradient-to-r from-green-500 to-green-600 text-white border border-green-500 shadow-sm',
        hover: 'hover:from-green-400 hover:to-green-500 hover:shadow-md hover:-translate-y-0.5',
        active: 'active:from-green-600 active:to-green-700 active:translate-y-0',
        disabled: 'disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed'
      }
    }
  };

  const sizeStyles = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-base',
    lg: 'px-6 py-3 text-lg'
  };

  const style = buttonStyles[effectiveTheme][variant];
  const sizeStyle = sizeStyles[size];

  const baseClasses = `
    inline-flex items-center justify-center font-medium rounded-md
    transition-all duration-200 ease-in-out
    focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500
    ${sizeStyle}
    ${style.base}
    ${!disabled && !loading ? style.hover : ''}
    ${!disabled && !loading ? style.active : ''}
    ${disabled ? style.disabled : ''}
  `.trim().replace(/\s+/g, ' ');

  return (
    <button
      className={baseClasses}
      onClick={onClick}
      disabled={disabled || loading}
      type="button"
    >
      {loading && (
        <svg
          className="animate-spin -ml-1 mr-2 h-4 w-4"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {icon && !loading && (
        <span className="mr-2">{icon}</span>
      )}
      {children}
    </button>
  );
};