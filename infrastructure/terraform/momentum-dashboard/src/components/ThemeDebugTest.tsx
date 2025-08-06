import React from 'react';
import { useTheme } from '../contexts/ThemeContext';

export function ThemeDebugTest() {
  const { mode, effectiveTheme } = useTheme();
  
  return (
    <div className="fixed top-4 right-4 z-50 p-4 border rounded-lg shadow-lg max-w-sm">
      {/* Test with inline styles to see if ANY theming works */}
      <div 
        style={{
          backgroundColor: document.documentElement.classList.contains('dark') ? '#1f2937' : '#ffffff',
          color: document.documentElement.classList.contains('dark') ? '#ffffff' : '#000000',
          padding: '16px',
          borderRadius: '8px',
          marginBottom: '12px'
        }}
      >
        <h3>Inline Style Test</h3>
        <p>This uses inline styles directly checking for dark class</p>
      </div>
      
      {/* Test with Tailwind classes */}
      <div className="bg-white dark:bg-gray-800 text-black dark:text-white p-4 rounded-lg mb-3">
        <h3>Tailwind Classes Test</h3>
        <p>This uses bg-white dark:bg-gray-800</p>
      </div>
      
      {/* Test with CSS custom properties */}
      <div 
        className="p-4 rounded-lg mb-3"
        style={{
          backgroundColor: 'var(--bg-primary, #ffffff)',
          color: 'var(--text-primary, #000000)'
        }}
      >
        <h3>CSS Variables Test</h3>
        <p>This uses CSS custom properties</p>
      </div>
      
      {/* Debug info */}
      <div className="text-xs space-y-1">
        <div>Mode: {mode}</div>
        <div>Effective: {effectiveTheme}</div>
        <div>HTML has dark class: {document.documentElement.classList.contains('dark') ? 'YES' : 'NO'}</div>
        <div>Document color scheme: {document.documentElement.style.colorScheme}</div>
      </div>
    </div>
  );
}