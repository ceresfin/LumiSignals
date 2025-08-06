import React, { ReactNode } from 'react';
import { Sparkles, TrendingUp, Target, Zap } from 'lucide-react';

interface SparkleCalloutProps {
  children: ReactNode;
  type?: 'signal' | 'success' | 'warning' | 'info';
  icon?: ReactNode;
  className?: string;
  animated?: boolean;
}

export const SparkleCallout: React.FC<SparkleCalloutProps> = ({
  children,
  type = 'signal',
  icon,
  className = '',
  animated = true
}) => {
  const getTypeConfig = () => {
    switch (type) {
      case 'signal':
        return {
          gradient: 'from-pipstop-primary via-pipstop-secondary to-pipstop-accent',
          icon: icon || <TrendingUp className="w-4 h-4" />,
          sparkleColor: 'text-white/80'
        };
      case 'success':
        return {
          gradient: 'from-pipstop-success via-pipstop-primary to-pipstop-secondary',
          icon: icon || <Target className="w-4 h-4" />,
          sparkleColor: 'text-white/80'
        };
      case 'warning':
        return {
          gradient: 'from-pipstop-warning via-pipstop-accent to-pipstop-primary',
          icon: icon || <Zap className="w-4 h-4" />,
          sparkleColor: 'text-white/80'
        };
      case 'info':
        return {
          gradient: 'from-pipstop-info via-pipstop-primary to-pipstop-secondary',
          icon: icon || <Sparkles className="w-4 h-4" />,
          sparkleColor: 'text-white/80'
        };
      default:
        return {
          gradient: 'from-pipstop-primary via-pipstop-secondary to-pipstop-accent',
          icon: icon || <TrendingUp className="w-4 h-4" />,
          sparkleColor: 'text-white/80'
        };
    }
  };

  const config = getTypeConfig();

  return (
    <div className={`relative overflow-hidden rounded-xl shadow-lg ${className}`}>
      {/* Main gradient background */}
      <div className={`bg-gradient-to-r ${config.gradient} ${animated ? 'animate-gradient' : ''} p-4`}>
        {/* Sparkle overlay */}
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-2 left-4">
            <Sparkles className={`w-2 h-2 ${config.sparkleColor} ${animated ? 'animate-pulse' : ''}`} />
          </div>
          <div className="absolute top-6 right-8">
            <Sparkles className={`w-3 h-3 ${config.sparkleColor} ${animated ? 'animate-pulse' : ''}`} style={{ animationDelay: '0.5s' }} />
          </div>
          <div className="absolute bottom-4 left-1/3">
            <Sparkles className={`w-2 h-2 ${config.sparkleColor} ${animated ? 'animate-pulse' : ''}`} style={{ animationDelay: '1s' }} />
          </div>
          <div className="absolute bottom-2 right-4">
            <Sparkles className={`w-2 h-2 ${config.sparkleColor} ${animated ? 'animate-pulse' : ''}`} style={{ animationDelay: '1.5s' }} />
          </div>
          <div className="absolute top-1/2 right-1/4">
            <Sparkles className={`w-2 h-2 ${config.sparkleColor} ${animated ? 'animate-pulse' : ''}`} style={{ animationDelay: '2s' }} />
          </div>
        </div>
        
        {/* Content */}
        <div className="relative z-10 flex items-center gap-3 text-white">
          <div className="flex-shrink-0">
            {config.icon}
          </div>
          <div className="flex-1 text-sm font-medium">
            {children}
          </div>
        </div>
      </div>
      
      {/* Subtle shimmer effect */}
      {animated && (
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -skew-x-12 animate-shimmer" />
      )}
    </div>
  );
};

export const PipStopAlert: React.FC<{
  pair: string;
  action: string;
  price: number;
  rr: number;
  className?: string;
}> = ({ pair, action, price, rr, className = '' }) => {
  return (
    <SparkleCallout type="signal" className={className}>
      <div className="flex items-center justify-between w-full">
        <div>
          <span className="font-semibold">{pair}</span>
          <span className="mx-2">•</span>
          <span>{action} at {price}</span>
        </div>
        <div className="text-right">
          <span className="text-xs opacity-90">R/R: </span>
          <span className="font-bold">{rr}</span>
        </div>
      </div>
    </SparkleCallout>
  );
};

export default SparkleCallout;