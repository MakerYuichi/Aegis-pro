import { type Incident } from '../utils/api';
import { AlertTriangle, Clock, Activity, CheckCircle, Zap } from 'lucide-react';
import { motion } from 'framer-motion';

interface StatsProps {
  incidents: Incident[];
}

export function Stats({ incidents }: StatsProps) {
  const total = incidents.length;
  const p0 = incidents.filter(i => i.severity === 'P0').length;
  const p1 = incidents.filter(i => i.severity === 'P1').length;
  const p2 = incidents.filter(i => i.severity === 'P2').length;
  const active = incidents.filter(i => i.status === 'active').length;
  const resolved = incidents.filter(i => i.status !== 'active').length;
  const operationalRate = total > 0 ? Math.round((resolved / total) * 100) : 100;

  const stats = [
    { label: 'Total Incidents', value: total, icon: Activity, color: 'text-brand-primary', bg: 'bg-brand-primary/10', border: 'border-brand-primary/20' },
    { label: 'P0 Critical', value: p0, icon: AlertTriangle, color: 'text-severity-critical', bg: 'bg-severity-critical/10', border: 'border-severity-critical/20' },
    { label: 'P1 High', value: p1, icon: AlertTriangle, color: 'text-severity-high', bg: 'bg-severity-high/10', border: 'border-severity-high/20' },
    { label: 'P2 Medium', value: p2, icon: Zap, color: 'text-severity-medium', bg: 'bg-severity-medium/10', border: 'border-severity-medium/20' },
    { label: 'Active Now', value: active, icon: Clock, color: 'text-brand-warning', bg: 'bg-brand-warning/10', border: 'border-brand-warning/20' },
    { label: 'Resolved', value: resolved, icon: CheckCircle, color: 'text-brand-success', bg: 'bg-brand-success/10', border: 'border-brand-success/20' },
  ];

  return (
    <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl overflow-hidden backdrop-blur-sm">
      {/* Header */}
      <div className="px-6 py-4 border-b border-light-border/50 dark:border-dark-border/50 bg-gradient-to-r from-brand-primary/5 to-brand-secondary/5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-gradient-to-br from-brand-primary/20 to-brand-secondary/20 rounded-xl shadow-sm">
            <Activity className="w-5 h-5 text-brand-primary" />
          </div>
          <div>
            <h3 className="text-base font-bold text-light-text dark:text-dark-text">Live Incident Summary</h3>
            <p className="text-xs text-light-muted dark:text-dark-muted">Real-time metrics</p>
          </div>
        </div>
        <div className="flex items-center gap-2 bg-brand-success/10 px-4 py-2 rounded-xl border border-brand-success/20">
          <span className="relative flex">
            <span className="w-2 h-2 rounded-full bg-brand-success animate-ping absolute" />
            <span className="w-2 h-2 rounded-full bg-brand-success" />
          </span>
          <span className="text-sm text-brand-success font-semibold">{operationalRate}% Resolved</span>
        </div>
      </div>

      <div className="p-5 grid grid-cols-3 md:grid-cols-6 gap-3">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ delay: i * 0.07, type: 'spring', stiffness: 220 }}
            whileHover={{ scale: 1.04, y: -2 }}
            className={`bg-gradient-to-br from-white/50 to-white/20 dark:from-dark-bg/50 dark:to-dark-bg/20 rounded-xl p-4 border ${stat.border} shadow-sm hover:shadow-md transition-all backdrop-blur-sm`}
          >
            <div className={`p-2 rounded-lg ${stat.bg} w-fit mb-3`}>
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
            </div>
            <p className={`text-3xl font-bold ${stat.color} mb-1 leading-none`}>{stat.value}</p>
            <p className="text-xs text-light-muted dark:text-dark-muted font-medium leading-tight">{stat.label}</p>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
