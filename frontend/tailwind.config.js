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
        // Light mode colors
        light: {
          bg: '#FFFFFF',
          surface: '#F8FAFC',
          border: '#E2E8F0',
          text: '#1E293B',
          muted: '#64748B',
          card: '#FFFFFF',
        },
        // Dark mode colors (high contrast)
        dark: {
          bg: '#0F172A',
          surface: '#1E293B',
          border: '#334155',
          text: '#F1F5F9',
          muted: '#94A3B8',
          card: '#1E293B',
        },
        // Brand colors
        brand: {
          primary: '#3B82F6',
          secondary: '#8B5CF6',
          accent: '#EC4899',
          success: '#10B981',
          warning: '#F59E0B',
          danger: '#EF4444',
        },
        // Severity colors (consistent across modes)
        severity: {
          critical: '#DC2626',
          high: '#EA580C',
          medium: '#D97706',
          low: '#059669',
        },
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'slide-in': 'slideIn 0.3s ease-out',
        'float': 'float 3s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'bounce-slow': 'bounce 2s infinite',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(59, 130, 246, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(59, 130, 246, 0.6)' },
        },
        slideIn: {
          '0%': { transform: 'translateY(-10px)', opacity: 0 },
          '100%': { transform: 'translateY(0)', opacity: 1 },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
      },
    },
  },
  plugins: [],
}