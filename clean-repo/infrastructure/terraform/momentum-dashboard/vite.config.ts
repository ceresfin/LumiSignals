import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['react', 'react-dom'],
          'charts': ['recharts', 'lightweight-charts'],
          'momentum': ['./src/services/momentum.ts', './src/hooks/useMomentumRanking.ts'],
          'utils': ['axios', 'lucide-react']
        }
      }
    }
  },
  define: {
    // Define environment variables for the build
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version),
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'recharts', 'axios', 'lucide-react']
  }
})