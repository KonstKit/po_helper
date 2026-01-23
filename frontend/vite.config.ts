/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Prefer explicit IPv4 loopback to avoid IPv6 (::1) mismatch with uvicorn bound to 127.0.0.1
  const apiUrl = env.VITE_API_URL || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: {
      port: 3001,
      open: false,
      proxy: {
        // Proxy API calls to backend to avoid CORS during dev
        '/api': {
          target: apiUrl,
          changeOrigin: true,
          ws: true, // enable websocket proxy for dev
          // Increase proxy timeouts for heavy requests
          timeout: 120000,
          proxyTimeout: 120000,
        },
      },
    },
    preview: {
      port: 4173,
      open: false,
    },
    build: {
      chunkSizeWarningLimit: 800,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            mui: ['@mui/material', '@mui/icons-material', '@mui/lab', '@emotion/react', '@emotion/styled'],
            charts: ['chart.js', 'react-chartjs-2', 'recharts'],
            state: ['@reduxjs/toolkit', 'react-redux', '@tanstack/react-query'],
            utilities: ['axios', 'date-fns'],
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      css: true,
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json', 'html'],
        exclude: [
          'node_modules/',
          'src/test/',
          '**/*.test.{ts,tsx}',
          '**/*.spec.{ts,tsx}',
        ],
      },
    },
  };
});
