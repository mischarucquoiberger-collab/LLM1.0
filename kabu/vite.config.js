import { copyFileSync, readdirSync, unlinkSync } from 'fs'
import { resolve, join } from 'path'
import base44 from "@base44/vite-plugin"
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/** Copy built index.html into the FastAPI templates dir so the server picks it up. */
function copyIndexToTemplates() {
  return {
    name: 'copy-index-to-templates',
    closeBundle() {
      const src = resolve(__dirname, '../app/static/index.html')
      const dst = resolve(__dirname, '../app/templates/index.html')
      try { copyFileSync(src, dst) } catch {}
    }
  }
}

/** Remove old hashed bundles from assets/ before each build to prevent accumulation. */
function cleanOldAssets() {
  return {
    name: 'clean-old-assets',
    buildStart() {
      const dir = resolve(__dirname, '../app/static/assets')
      try {
        for (const f of readdirSync(dir)) {
          if (/\.(js|css)$/.test(f)) unlinkSync(join(dir, f))
        }
      } catch {}
    }
  }
}

// https://vite.dev/config/
export default defineConfig({
  logLevel: 'error', // Suppress warnings, only show errors
  base: process.env.NODE_ENV === 'production' ? '/static/' : '/',
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/start': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/status': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/stream': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/download': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/jobs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../app/static',
    emptyOutDir: false,  // Don't delete other static files
    rollupOptions: {
      output: {
        assetFileNames: 'assets/[name]-[hash][extname]',
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      }
    }
  },
  plugins: [
    cleanOldAssets(),
    base44({
      legacySDKImports: process.env.BASE44_LEGACY_SDK_IMPORTS === 'true',
      hmrNotifier: true,
      navigationNotifier: true,
      visualEditAgent: true
    }),
    react(),
    copyIndexToTemplates(),
  ]
});
