import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import App from './App';
import ArchitecturePage from './pages/ArchitecturePage';
import { ThemeProvider } from './contexts/ThemeContext';

function AppRouter() {
  return (
    <ThemeProvider>
      <Router>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/architecture" element={<ArchitecturePage />} />
        </Routes>
      </Router>
    </ThemeProvider>
  );
}

export default AppRouter;