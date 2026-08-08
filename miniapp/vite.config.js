import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Telegram loads Mini Apps over HTTPS inside an iframe/WebView; when
    // testing through a tunnel (ngrok etc.) accept any forwarded host.
    allowedHosts: true,
  },
});
