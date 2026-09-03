import { Link, useLocation } from 'react-router-dom';
import { Shield, Zap, Moon, Sun, LayoutDashboard, AlertTriangle, Server, Users, Settings as SettingsIcon } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export function Navbar() {
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/incidents', label: 'Incidents', icon: AlertTriangle },
    { path: '/services', label: 'Services', icon: Server },
    { path: '/oncall', label: 'On-Call', icon: Users },
    { path: '/approvals', label: 'Approvals', icon: Zap },
    { path: '/settings', label: 'Settings', icon: SettingsIcon },
  ];

  return (
    <nav className="bg-white dark:bg-dark-bg border-b border-light-border dark:border-dark-border shadow-sm transition-colors">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between py-4">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-3 group">
            <div className="relative">
              <div className="absolute inset-0 bg-brand-primary/20 rounded-lg blur opacity-0 group-hover:opacity-100 transition-opacity"></div>
              <Shield className="w-10 h-10 text-brand-primary relative z-10" />
              <Zap className="w-4 h-4 text-brand-accent absolute -top-1 -right-1 z-20 animate-pulse" />
            </div>
            <div>
              <span className="text-2xl font-bold text-light-text dark:text-dark-text gradient-text">
                AEGIS PRO
              </span>
              <span className="text-xs bg-brand-primary/10 text-brand-primary px-2 py-0.5 rounded-full ml-2 font-medium">
                v2.0
              </span>
            </div>
          </Link>
          
          {/* Navigation */}
          <div className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200 font-medium ${
                    isActive
                      ? 'bg-brand-primary text-white shadow-md'
                      : 'text-light-muted dark:text-dark-muted hover:bg-light-surface dark:hover:bg-dark-surface hover:text-light-text dark:hover:text-dark-text'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="text-sm">{item.label}</span>
                </Link>
              );
            })}
          </div>
          
          {/* Right Side */}
          <div className="flex items-center gap-3">
            {/* Status Indicator */}
            <div className="hidden sm:flex items-center gap-2 bg-brand-success/10 px-3 py-1.5 rounded-lg border border-brand-success/20">
              <span className="w-2 h-2 rounded-full bg-brand-success animate-pulse"></span>
              <span className="text-xs text-brand-success font-medium">All Systems Operational</span>
            </div>
            
            {/* Theme Toggle */}
            <button
              onClick={toggleTheme}
              className="p-2.5 rounded-lg bg-light-surface dark:bg-dark-surface hover:bg-light-border dark:hover:bg-dark-border text-light-text dark:text-dark-text transition-all duration-200 border border-light-border dark:border-dark-border"
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? (
                <Sun className="w-5 h-5 text-brand-warning" />
              ) : (
                <Moon className="w-5 h-5 text-brand-primary" />
              )}
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}