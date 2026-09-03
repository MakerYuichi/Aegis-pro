import { type Incident } from '../utils/api';
import { AlertTriangle, Clock, Activity, TrendingUp, TrendingDown, Shield } from 'lucide-react';
import { motion } from 'framer-motion';

interface StatsProps {
  incidents: Incident[];
}

export function Stats({ incidents }: StatsProps) {
  const total = incidents.length;
  const p0 = incidents.filter(i => i.severity === 'P0').length;
  const p1 = incidents.filter(i => i.severity === 'P1').length;
  const active = incidents.filter(i => i.status === 'active').length;

  // Calculate operational rate
  const operationalRate = total > 0 ? Math.round(((total - active) / total) * 100) : 100;

  // Calculate mock trends (in real app, compare with previous period)
  const trends = {
    total: { value: 12, direction: 'up' },
    p0: { value: 3, direction: 'up' },
    p1: { value: -2, direction: 'down' },
    active: { value: 5, direction: 'up' },
  };

  const stats = [
    {
      label: 'Total Incidents',
      value: total,
      icon: Activity,
      color: 'text-brand-primary',
      bg: 'bg-brand-primary/10',
      border: 'border-brand-primary/20',
      trend: trends.total,
    },
    {
      label: 'P0 Critical',
      value: p0,
      icon: AlertTriangle,
      color: 'text-severity-critical',
      bg: 'bg-severity-critical/10',
      border: 'border-severity-critical/20',
      trend: trends.p0,
    },
    {
      label: 'P1 High',
      value: p1,
      icon: AlertTriangle,
      color: 'text-severity-high',
      bg: 'bg-severity-high/10',
      border: 'border-severity-high/20',
      trend: trends.p1,
    },
    {
      label: 'Active Incidents',
      value: active,
      icon: Clock,
      color: 'text-brand-warning',
      bg: 'bg-brand-warning/10',
      border: 'border-brand-warning/20',
      trend: trends.active,
    },
  ];

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      <div className="p-6 border-b border-light-border dark:border-dark-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-brand-primary/10 rounded-lg">
              <Activity className="w-5 h-5 text-brand-primary" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-light-text dark:text-dark-text">Live Incident Summary</h3>
              <p className="text-sm text-light-muted dark:text-dark-muted">Real-time incident metrics</p>
            </div>
          </div>
          <div className="flex items-center gap-2 bg-brand-success/10 px-3 py-1.5 rounded-lg border border-brand-success/20">
            <Shield className="w-4 h-4 text-brand-success" />
            <span className="text-sm text-brand-success font-medium">{operationalRate}% Operational</span>
          </div>
        </div>
      </div>

      <div className="p-6 grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((stat, index) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
            className={`bg-light-surface dark:bg-dark-surface rounded-xl p-4 border ${stat.border} hover:bg-light-border dark:hover:bg-dark-border transition-all`}
          >
            <div className="flex items-center justify-between mb-2">
              <div className={`p-2 rounded-lg ${stat.bg}`}>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className={stat.trend.direction === 'up' ? 'text-severity-critical' : 'text-brand-success'}>
                  {stat.trend.direction === 'up' ? '+' : ''}{stat.trend.value}
                </span>
                {stat.trend.direction === 'up' ? (
                  <TrendingUp className="w-3 h-3 text-severity-critical" />
                ) : (
                  <TrendingDown className="w-3 h-3 text-brand-success" />
                )}
              </div>
            </div>
            <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
            <p className="text-xs text-light-muted dark:text-dark-muted mt-1">{stat.label}</p>
          </motion.div>
        ))}
      </div>
    </div>
  );
}