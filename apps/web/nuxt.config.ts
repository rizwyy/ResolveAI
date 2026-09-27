export default defineNuxtConfig({
  ssr: false,
  modules: ['@nuxtjs/tailwindcss', '@nuxt/eslint'],
  css: ['~/assets/css/main.css'],
  runtimeConfig: {
    public: { apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1' }
  },
  app: { head: { title: 'ResolveAI', meta: [{ name: 'description', content: 'Safe customer support operations' }] } },
  typescript: { strict: true }
})
