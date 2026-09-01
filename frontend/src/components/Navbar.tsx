import { Link } from 'react-router-dom';
import { AlertTriangle, Shield, Zap, Moon, Sun } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export function Navbar() {
  const { theme, toggleTheme } = useTheme();

  return (
    <nav className="bg-white dark:bg-dark-surface shadow-md border-b border-gray-200 dark:border-dark-border transition-colors">
      <div className="container mx-auto px-4 py-3 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2">
          <div className="relative">
            <Shield className="w-8 h-8 text-primary-500" />
            <Zap className="w-3 h-3 text-yellow-400 absolute -top-0.5 -right-0.5" />
          </div>
          <div>
            <span className="text-xl font-bold text-primary-500">AEGIS PRO</span>
            <span className="text-xs bg-gray-100 dark:bg-dark-border px-2 py-0.5 rounded-full text-gray-600 dark:text-dark-muted ml-2">v1.0</span>
          </div>
        </Link>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
            <span className="text-xs text-gray-500 dark:text-dark-muted hidden sm:inline">All systems operational</span>
          </div>
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-border transition"
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? (
              <Sun className="w-5 h-5 text-yellow-400" />
            ) : (
              <Moon className="w-5 h-5 text-gray-600" />
            )}
          </button>
          <Link
            to="/"
            className="text-sm text-gray-500 dark:text-dark-muted hover:text-primary-500 transition"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </nav>
  );
}