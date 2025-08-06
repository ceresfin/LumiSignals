import React, { useState, useEffect } from 'react';

const ThemeToggle = () => {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    // Get theme from localStorage or default to light
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    const shouldBeDark = savedTheme === 'dark' || (!savedTheme && prefersDark);
    
    setIsDark(shouldBeDark);
    
    if (shouldBeDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, []);

  const toggleTheme = () => {
    const newTheme = isDark ? 'light' : 'dark';
    
    setIsDark(!isDark);
    localStorage.setItem('theme', newTheme);
    
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  return (
    <button
      onClick={toggleTheme}
      className="flex items-center gap-2 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark px-3 py-1.5 rounded-full text-sm text-text-primary-light dark:text-text-primary-dark hover:bg-elevated-light dark:hover:bg-elevated-dark hover:border-pipstop-primary/30 transition-all duration-200"
    >
      {isDark ? (
        <>
          <span className="text-base">☀️</span>
          <span>Light</span>
        </>
      ) : (
        <>
          <span className="text-base">🌙</span>
          <span>Dark</span>
        </>
      )}
    </button>
  );
};

export { ThemeToggle };
export default ThemeToggle;