/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    assetsDir: 'static',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:3847',
      '/events': {
        target: 'http://localhost:3847',
        ws: true,
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/__tests__/**/*.test.ts'],
  },
})
