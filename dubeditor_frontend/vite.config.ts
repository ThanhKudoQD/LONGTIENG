import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '/home/dmin/nano/public/dubeditor',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/dub': 'http://127.0.0.1:8809',
      '/dub/ws': { target: 'ws://127.0.0.1:8809', ws: true }
    }
  }
})
