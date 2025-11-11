import { fileURLToPath, URL } from "node:url";
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false
  },
  server: {
    host: true,
    port: 5173
  }
,
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } }
});
