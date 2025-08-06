/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class', // Enable dark mode with class strategy
  theme: {
    extend: {
      colors: {
        // LumiTrade Institutional Theme System
        background: {
          light: '#F7F6F2',      // Fog Gray - professional light
          dark: '#121212',       // Dark Mode Base
        },
        surface: {
          light: '#FFFFFF',      // Pure white cards
          dark: '#1E1E1E',       // Surface panels
        },
        elevated: {
          light: '#F9F9F9',      // Slightly elevated surfaces
          dark: '#232323',       // Elevated surfaces
        },
        text: {
          primary: {
            light: '#1D1E1F',    // Deep Charcoal
            dark: '#F1F1F1',     // Light primary text
          },
          secondary: {
            light: '#6B7280',    // Gray 600
            dark: '#B3B3B3',     // Light secondary text
          },
          muted: {
            light: '#9CA3AF',    // Gray 400
            dark: '#8A8A8A',     // Muted text
          },
          disabled: {
            light: '#D1D5DB',    // Gray 300
            dark: '#5C5C5C',     // Disabled text
          },
        },
        border: {
          light: '#E5E5E5',      // Light borders
          dark: '#2C2C2C',       // Dark borders
          medium: {
            light: '#D4D4D4',
            dark: '#3B3B3B',
          },
          strong: {
            light: '#B8B8B8',
            dark: '#525252',
          },
        },
        // LumiTrade Brand Colors - Institutional Grade
        lumitrade: {
          sage: {
            light: '#8A9C91',    // Sage Silver
            dark: '#A2C4BA',     // Original Sage
          },
          rose: {
            light: '#B4837D',    // Rose Gold
            dark: '#D9AAB1',     // Original Rose
          },
          gold: '#C2A565',       // Consistent across modes
          charcoal: '#121212',
          graphite: '#1E1E1E',
          'fog-gray': '#2C2C2C',
          'soft-ash': '#3B3B63',
          'sage-haze': '#A2C8A1',
          'misty-olive': '#32A0A8',
          'soft-eucalyptus': '#C9F7CF',
          'blush-mist': '#D9A2A1',
          'rosy-veil': '#CF4505',
          'dusty-rose': '#A67D8B',
          'petal-beige': '#FFE4B3',
          'honey-pearl': '#FFE4B3',
          'moonlit-taupe': '#B6E6C4',
          'soft-champagne': '#F7F2E6',
        },
        // PipStop Brand Colors (Legacy Support)
        pipstop: {
          primary: '#8FC9CF',    // Slate Aqua
          secondary: '#A2C4BA',  // Sage Haze
          accent: '#FFE4B3',     // Honey Pearl
          success: '#C7D9C5',    // Soft Green
          danger: '#C26A6A',     // Soft Red
          warning: '#E6C547',    // Warning yellow
          info: '#7CB3D9',       // Info blue
        },
        // Momentum-specific colors
        momentum: {
          'strong-bullish': '#A2C8A1',
          'weak-bullish': '#C9F7CF',
          'neutral': '#2C2C2C',
          'weak-bearish': '#D9A2A1',
          'strong-bearish': '#CF4505',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'bounce-slow': 'bounce 2s infinite',
        'gradient': 'gradient 3s ease infinite',
        'shimmer': 'shimmer 2s linear infinite',
      },
      keyframes: {
        gradient: {
          '0%, 100%': {
            'background-size': '200% 200%',
            'background-position': 'left center'
          },
          '50%': {
            'background-size': '200% 200%',
            'background-position': 'right center'
          },
        },
        shimmer: {
          '0%': {
            transform: 'translateX(-100%) skewX(-12deg)'
          },
          '100%': {
            transform: 'translateX(200%) skewX(-12deg)'
          },
        }
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'momentum': '0 4px 20px rgba(162, 200, 161, 0.3)',
        'glow': '0 0 20px rgba(162, 200, 161, 0.4)',
        'glow-red': '0 0 20px rgba(207, 69, 5, 0.4)',
      },
      gradientColorStops: {
        'lumitrade-primary': '#A2C8A1',
        'lumitrade-secondary': '#32A0A8',
      }
    },
  },
  plugins: [],
}