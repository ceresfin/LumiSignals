import React from 'react'
import ReactDOM from 'react-dom/client'
import AppRouter from './AppRouter.tsx'
import './App.css'

// EMERGENCY VERSION CHECK
console.log('🚨🚨🚨 LUMISIGNALS VERSION 4.0 - EST TIMEZONE FIX ATTEMPT 2 - ' + new Date().toISOString());

ReactDOM.createRoot(document.getElementById('root')!).render(
  <AppRouter />
)