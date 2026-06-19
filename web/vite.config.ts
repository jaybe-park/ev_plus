import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5765,
    strictPort: true,  // 포트 사용 중이면 다른 포트로 넘어가지 않고 에러
  },
})
