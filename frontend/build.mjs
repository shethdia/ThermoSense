import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const root = path.dirname(fileURLToPath(import.meta.url))

await build({
  configFile: false,
  root,
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('recharts') || id.includes('d3-')) return 'charts'
          if (id.includes('react-router') || id.includes('@remix-run') || id.includes('/react/') || id.includes('react-dom') || id.includes('scheduler')) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
