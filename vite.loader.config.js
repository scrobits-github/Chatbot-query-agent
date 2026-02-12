import { defineConfig } from 'vite'

export default defineConfig({
    build: {
        emptyOutDir: false, // Don't delete dist from the main build
        lib: {
            entry: 'src/iframe-loader.js',
            name: 'ChatbotLoader',
            fileName: () => 'chatbot-loader.js',
            formats: ['iife'],
        },
        rollupOptions: {
            output: {
                extend: true,
            },
        },
    },
    define: {
        "process.env": {},
    },
})
