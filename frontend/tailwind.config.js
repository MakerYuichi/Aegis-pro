/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#EEEAFF',
          100: '#D4CCFF',
          200: '#B8ADFF',
          300: '#9C8EFF',
          400: '#806EFF',
          500: '#6C63FF',
          600: '#5A52D5',
          700: '#4A44B0',
          800: '#3A368A',
          900: '#2A2864',
          950: '#1A1A3E',
        },
        severity: {
          critical: '#FF4444',
          high: '#FF8800',
          medium: '#FFCC00',
          low: '#22C55E',
        },
        dark: {
          bg: '#0D1117',
          surface: '#161B22',
          border: '#30363D',
          text: '#E6EDF3',
          muted: '#8B949E',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(108, 99, 255, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(108, 99, 255, 0.6)' },
        },
        slideIn: {
          '0%': { transform: 'translateY(-10px)', opacity: 0 },
          '100%': { transform: 'translateY(0)', opacity: 1 },
        },
      },
    },
  },
  plugins: [],
}