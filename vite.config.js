import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [tailwindcss(), react()],
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        chatbot: 'chatbot.html',
      },
    },
  },
  define: {
    "process.env": {},
  },
})
