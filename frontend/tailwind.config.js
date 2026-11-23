/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0b1220', // app background
          900: '#0f172a', // panel background
          850: '#131c2e', // raised panel
          800: '#1a2438', // hover / input background
          700: '#243349', // borders (lighter)
          600: '#2f425c',
        },
        accent: {
          DEFAULT: '#10b981',
          dim: '#059669',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
}
