import { type Incident } from '../utils/api';
import { AlertTriangle, CheckCircle, Clock, Activity, TrendingUp, TrendingDown } from 'lucide-react';
import { motion } from 'framer-motion';

interface StatsProps {
  incidents: Incident[];
}

export function Stats({ incidents }: StatsProps) {
  const total = incidents.length;
  const p0 = incidents.filter(i => i.severity === 'P0').length;
  const p1 = incidents.filter(i => i.severity === 'P1').length;
  const active = incidents.filter(i => i.status === 'active').length;
  const resolved = incidents.filter(i => i.status === 'resolved').length;

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
      color: 'text-primary-500',
      bg: 'bg-primary-50 dark:bg-primary-950/20',
      border: 'border-primary-500',
      trend: trends.total,
    },
    {
      label: 'P0 Critical',
      value: p0,
      icon: AlertTriangle,
      color: 'text-severity-critical',
      bg: 'bg-red-50 dark:bg-red-950/20',
      border: 'border-severity-critical',
      trend: trends.p0,
    },
    {
      label: 'P1 High',
      value: p1,
      icon: AlertTriangle,
      color: 'text-severity-high',
      bg: 'bg-orange-50 dark:bg-orange-950/20',
      border: 'border-severity-high',
      trend: trends.p1,
    },
    {
      label: 'Active Incidents',
      value: active,
      icon: Clock,
      color: 'text-yellow-500',
      bg: 'bg-yellow-50 dark:bg-yellow-950/20',
      border: 'border-yellow-500',
      trend: trends.active,
    },
  ];

  return (
    <>
      {stats.map((stat, index) => (
        <motion.div
          key={stat.label}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.1 }}
          className={`bg-white dark:bg-dark-surface rounded-xl shadow-lg p-6 border-l-4 ${stat.border} hover:shadow-xl transition-shadow`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${stat.bg}`}>
                <stat.icon className={`w-5 h-5 ${stat.color}`} />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-dark-muted">{stat.label}</p>
                <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
              </div>
            </div>
            <div className="flex items-center gap-1 text-sm">
              <span className={stat.trend.direction === 'up' ? 'text-red-500' : 'text-green-500'}>
                {stat.trend.direction === 'up' ? '+' : ''}{stat.trend.value}
              </span>
              {stat.trend.direction === 'up' ? (
                <TrendingUp className="w-4 h-4 text-red-500" />
              ) : (
                <TrendingDown className="w-4 h-4 text-green-500" />
              )}
            </div>
          </div>
          <div className="mt-2 h-1 w-full bg-gray-100 dark:bg-dark-border rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${stat.border.replace('border-', 'bg-')}`}
              style={{ width: `${Math.min((stat.value / 10) * 100, 100)}%` }}
            />
          </div>
        </motion.div>
      ))}
    </>
  );
}