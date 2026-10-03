import { defineConfig } from 'vitest/config'

// Same shape as the desktop workspace: plain Node environment plus a setup
// file that supplies the browser-provided globals Node may lack. Without an
// explicit config the suite runs on vitest defaults and the CloseEvent guard
// only survives where the runtime happens to ship the global.
export default defineConfig({
  test: {
    environment: 'node',
    setupFiles: ['./vitest.setup.ts'],
  },
})
