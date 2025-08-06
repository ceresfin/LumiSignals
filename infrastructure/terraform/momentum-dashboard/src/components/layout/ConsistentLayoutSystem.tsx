import React, { useState, useEffect, useRef } from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import { InstitutionalThemeControls } from '../ui/InstitutionalThemeControls';
import { Activity, TrendingUp, BarChart3, Settings, Bell, Search, Menu, X } from 'lucide-react';

interface ConsistentLayoutSystemProps {
  children: React.ReactNode;
  showSidebar?: boolean;
  sidebarCollapsed?: boolean;
  onSidebarToggle?: (collapsed: boolean) => void;
}

// Visual anchor elements that remain consistent across themes
const VisualAnchor = ({ 
  type, 
  theme, 
  isActive = false 
}: { 
  type: 'logo' | 'nav' | 'status' | 'accent';
  theme: any;
  isActive?: boolean;
}) => {
  const anchorStyles = {
    logo: {
      // Logo area maintains consistent positioning and scale
      position: 'relative' as const,
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '16px',
      minHeight: '64px' // Consistent header height
    },
    nav: {
      // Navigation items maintain consistent spacing and hierarchy
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      padding: '12px 16px',
      borderRadius: '8px',
      transition: 'all 0.2s ease',
      cursor: 'pointer',
      backgroundColor: isActive ? theme.surface : 'transparent',
      color: isActive ? theme.text : theme.textSecondary,
      ':hover': {
        backgroundColor: theme.surface
      }
    },
    status: {
      // Status indicators maintain consistent positioning
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      padding: '8px 12px',
      borderRadius: '6px',
      fontSize: '12px',
      fontWeight: '500',
      backgroundColor: `${theme.bullishPrimary}20`,
      color: theme.bullishPrimary,
      border: `1px solid ${theme.bullishPrimary}30`
    },
    accent: {
      // Accent elements maintain brand consistency
      width: '3px',
      height: '100%',
      backgroundColor: theme.accent,
      borderRadius: '0 2px 2px 0',
      position: 'absolute' as const,
      left: '0',
      top: '0'
    }
  };

  return <div style={anchorStyles[type]} />;
};

// Consistent navigation structure
const NavigationStructure = ({ 
  theme, 
  collapsed = false,
  currentPath = '/dashboard'
}: { 
  theme: any;
  collapsed: boolean;
  currentPath?: string;
}) => {
  const navigationItems = [
    { 
      id: 'dashboard', 
      label: 'Dashboard', 
      icon: BarChart3, 
      path: '/dashboard',
      description: 'Real-time market overview'
    },
    { 
      id: 'analysis', 
      label: 'Analysis', 
      icon: TrendingUp, 
      path: '/analysis',
      description: 'Technical analysis tools'
    },
    { 
      id: 'monitoring', 
      label: 'Monitoring', 
      icon: Activity, 
      path: '/monitoring',
      description: 'Live trading monitor'
    },
    { 
      id: 'settings', 
      label: 'Settings', 
      icon: Settings, 
      path: '/settings',
      description: 'System preferences'
    }
  ];

  return (
    <nav className="space-y-2" role="navigation" aria-label="Main navigation">
      {navigationItems.map((item) => {
        const Icon = item.icon;
        const isActive = currentPath === item.path;
        
        return (
          <div
            key={item.id}
            className={`
              relative flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 cursor-pointer
              ${isActive 
                ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' 
                : 'hover:bg-gray-50 dark:hover:bg-gray-700/50 text-gray-700 dark:text-gray-300'
              }
            `}
            style={{
              backgroundColor: isActive ? `${theme.accent}20` : 'transparent',
              color: isActive ? theme.accent : theme.textSecondary
            }}
            role="menuitem"
            aria-current={isActive ? 'page' : undefined}
            title={collapsed ? item.label : item.description}
          >
            {/* Active indicator */}
            {isActive && (
              <div 
                className="absolute left-0 top-0 w-1 h-full rounded-r-full"
                style={{ backgroundColor: theme.accent }}
              />
            )}
            
            <Icon className="w-5 h-5 flex-shrink-0" />
            
            {!collapsed && (
              <div className="flex-1">
                <div className="font-medium">{item.label}</div>
                <div className="text-xs opacity-75">{item.description}</div>
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
};

// Consistent header structure
const HeaderStructure = ({ 
  theme, 
  onSidebarToggle,
  sidebarCollapsed 
}: { 
  theme: any;
  onSidebarToggle: (collapsed: boolean) => void;
  sidebarCollapsed: boolean;
}) => {
  return (
    <header 
      className="sticky top-0 z-40 flex items-center justify-between px-6 py-4 border-b backdrop-blur-sm"
      style={{
        backgroundColor: `${theme.background}95`,
        borderColor: theme.border
      }}
    >
      {/* Left section - Logo and navigation */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => onSidebarToggle(!sidebarCollapsed)}
          className="lg:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          style={{ color: theme.textSecondary }}
          aria-label="Toggle sidebar"
        >
          <Menu className="w-5 h-5" />
        </button>
        
        <div className="flex items-center gap-3">
          <div 
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-white"
            style={{ backgroundColor: theme.accent }}
          >
            LT
          </div>
          <div>
            <h1 className="text-lg font-bold" style={{ color: theme.text }}>
              LumiTrade
            </h1>
            <p className="text-xs" style={{ color: theme.textSecondary }}>
              Institutional Platform
            </p>
          </div>
        </div>
      </div>

      {/* Center section - Search */}
      <div className="hidden md:flex items-center flex-1 max-w-md mx-8">
        <div className="relative w-full">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4" style={{ color: theme.textSecondary }} />
          <input
            type="text"
            placeholder="Search markets, strategies..."
            className="w-full pl-10 pr-4 py-2 rounded-lg border transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            style={{
              backgroundColor: theme.surface,
              borderColor: theme.border,
              color: theme.text
            }}
          />
        </div>
      </div>

      {/* Right section - Theme controls and status */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-green-100 dark:bg-green-900/20">
          <Activity className="w-3 h-3 text-green-600 dark:text-green-400" />
          <span className="text-xs font-medium text-green-700 dark:text-green-300">
            Markets Open
          </span>
        </div>
        
        <button
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 relative"
          style={{ color: theme.textSecondary }}
          aria-label="Notifications"
        >
          <Bell className="w-5 h-5" />
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full" />
        </button>
        
        <InstitutionalThemeControls 
          placement="header" 
          priority="primary"
          showSystemStatus={false}
        />
      </div>
    </header>
  );
};

// Consistent sidebar structure
const SidebarStructure = ({ 
  theme, 
  collapsed = false,
  onToggle 
}: { 
  theme: any;
  collapsed: boolean;
  onToggle: (collapsed: boolean) => void;
}) => {
  return (
    <aside 
      className={`
        fixed lg:relative top-0 left-0 z-30 h-full border-r transition-all duration-300 backdrop-blur-sm
        ${collapsed ? 'w-16' : 'w-64'}
      `}
      style={{
        backgroundColor: `${theme.surface}95`,
        borderColor: theme.border
      }}
    >
      {/* Sidebar header */}
      <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: theme.border }}>
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div 
              className="w-6 h-6 rounded flex items-center justify-center font-bold text-white text-sm"
              style={{ backgroundColor: theme.accent }}
            >
              LT
            </div>
            <span className="font-semibold" style={{ color: theme.text }}>
              LumiTrade
            </span>
          </div>
        )}
        
        <button
          onClick={() => onToggle(!collapsed)}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
          style={{ color: theme.textSecondary }}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <Menu className="w-4 h-4" /> : <X className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation */}
      <div className="p-4 flex-1 overflow-y-auto">
        <NavigationStructure theme={theme} collapsed={collapsed} />
      </div>

      {/* Sidebar footer */}
      <div className="p-4 border-t" style={{ borderColor: theme.border }}>
        {!collapsed && (
          <InstitutionalThemeControls 
            placement="sidebar" 
            priority="secondary"
            compactMode={true}
            showSystemStatus={true}
          />
        )}
      </div>
    </aside>
  );
};

// Main layout system with consistent structure
export const ConsistentLayoutSystem: React.FC<ConsistentLayoutSystemProps> = ({
  children,
  showSidebar = true,
  sidebarCollapsed = false,
  onSidebarToggle
}) => {
  const { effectiveTheme, isTransitioning } = useTheme();
  const [isSidebarOpen, setIsSidebarOpen] = useState(!sidebarCollapsed);
  const [preservedScrollPosition, setPreservedScrollPosition] = useState(0);
  const mainContentRef = useRef<HTMLDivElement>(null);

  const theme = {
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      text: '#1f2937',
      textSecondary: '#6b7280',
      textMuted: '#9ca3af',
      border: '#e5e7eb',
      accent: '#8A9C91', // Sage light mode
      bullishPrimary: '#047857'
    },
    dark: {
      background: '#1e1e1e',
      surface: '#2c2c2c',
      text: '#f1f1f1',
      textSecondary: '#b3b3b3',
      textMuted: '#8a8a8a',
      border: '#3b3b3b',
      accent: '#A2C4BA', // Sage dark mode
      bullishPrimary: '#34d399'
    }
  }[effectiveTheme];

  // Preserve scroll position during theme transitions
  useEffect(() => {
    if (isTransitioning) {
      setPreservedScrollPosition(mainContentRef.current?.scrollTop || 0);
    } else {
      // Restore scroll position after transition
      setTimeout(() => {
        if (mainContentRef.current) {
          mainContentRef.current.scrollTop = preservedScrollPosition;
        }
      }, 50);
    }
  }, [isTransitioning, preservedScrollPosition]);

  // Handle sidebar toggle
  const handleSidebarToggle = (collapsed: boolean) => {
    setIsSidebarOpen(!collapsed);
    onSidebarToggle?.(collapsed);
  };

  return (
    <div 
      className="flex h-screen overflow-hidden transition-colors duration-300"
      style={{ backgroundColor: theme.background }}
    >
      {/* Sidebar */}
      {showSidebar && (
        <SidebarStructure 
          theme={theme}
          collapsed={!isSidebarOpen}
          onToggle={handleSidebarToggle}
        />
      )}

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <HeaderStructure 
          theme={theme}
          onSidebarToggle={handleSidebarToggle}
          sidebarCollapsed={!isSidebarOpen}
        />

        {/* Main content */}
        <main 
          ref={mainContentRef}
          className="flex-1 overflow-y-auto"
          style={{ backgroundColor: theme.surface }}
        >
          {/* Transition overlay during theme changes */}
          {isTransitioning && (
            <div 
              className="fixed inset-0 z-50 pointer-events-none transition-opacity duration-300"
              style={{
                backgroundColor: theme.background,
                opacity: 0.3
              }}
            />
          )}
          
          {children}
        </main>
      </div>
    </div>
  );
};

// Hook for maintaining layout consistency
export const useLayoutConsistency = () => {
  const { effectiveTheme, isTransitioning } = useTheme();
  const [layoutMetrics, setLayoutMetrics] = useState({
    headerHeight: 64,
    sidebarWidth: 256,
    sidebarCollapsedWidth: 64,
    contentPadding: 24
  });

  // Consistent spacing system
  const spacing = {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
    xxl: 48
  };

  // Consistent border radius system
  const borderRadius = {
    sm: 4,
    md: 8,
    lg: 12,
    xl: 16
  };

  // Consistent shadow system
  const shadows = {
    sm: '0 1px 2px rgba(0, 0, 0, 0.1)',
    md: '0 4px 12px rgba(0, 0, 0, 0.1)',
    lg: '0 8px 24px rgba(0, 0, 0, 0.15)',
    xl: '0 12px 32px rgba(0, 0, 0, 0.2)'
  };

  return {
    layoutMetrics,
    spacing,
    borderRadius,
    shadows,
    isTransitioning,
    theme: effectiveTheme
  };
};

// Layout presets for different page types
export const LayoutPresets = {
  Dashboard: (props: any) => (
    <ConsistentLayoutSystem 
      showSidebar={true}
      sidebarCollapsed={false}
      {...props}
    />
  ),
  
  Analysis: (props: any) => (
    <ConsistentLayoutSystem 
      showSidebar={true}
      sidebarCollapsed={true}
      {...props}
    />
  ),
  
  Fullscreen: (props: any) => (
    <ConsistentLayoutSystem 
      showSidebar={false}
      {...props}
    />
  )
};