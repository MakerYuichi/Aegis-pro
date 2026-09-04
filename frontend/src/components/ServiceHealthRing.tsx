import { Activity, CheckCircle, AlertTriangle, XCircle, Users, GitBranch } from 'lucide-react';
import { motion } from 'framer-motion';
import { type Service, type Incident } from '../utils/api';

interface ServiceHealthRingProps {
  services: Service[];
  incidents: Incident[];
}

export function ServiceHealthRing({ services, incidents }: ServiceHealthRingProps) {
  const calcHealth = (name: string) => {
    const active = incidents.filter(i => i.service_name === name && i.status === 'active').length;
    const total = incidents.filter(i => i.service_name === name).length;
    if (active === 0 && total === 0) return 100;
    if (active > 0) return Math.max(0, 100 - active * 20);
    return Math.max(0, 100 - total * 5);
  };

  const overallHealth = services.length > 0
    ? Math.round(services.reduce((a, s) => a + calcHealth(s.name), 0) / services.length)
    : 100;

  const healthColor = (h: number) =>
    h >= 95 ? '#10B981' : h >= 80 ? '#F59E0B' : h >= 60 ? '#EA580C' : '#DC2626';

  const healthBg = (h: number) =>
    h >= 95 ? 'bg-brand-success' : h >= 80 ? 'bg-brand-warning' : h >= 60 ? 'bg-severity-high' : 'bg-severity-critical';

  const healthText = (h: number) =>
    h >= 95 ? 'text-brand-success' : h >= 80 ? 'text-brand-warning' : h >= 60 ? 'text-severity-high' : 'text-severity-critical';

  const statusIcon = (h: number) => {
    if (h >= 95) return <CheckCircle className="w-4 h-4 text-brand-success" />;
    if (h >= 80) return <Activity className="w-4 h-4 text-brand-warning" />;
    if (h >= 60) return <AlertTriangle className="w-4 h-4 text-severity-high" />;
    return <XCircle className="w-4 h-4 text-severity-critical" />;
  };

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-light-border dark:border-dark-border flex items-center gap-3">
        <div className="p-2 bg-brand-success/10 rounded-lg">
          <Activity className="w-5 h-5 text-brand-success" />
        </div>
        <div>
          <h3 className="text-base font-bold text-light-text dark:text-dark-text">Service Health</h3>
          <p className="text-xs text-light-muted dark:text-dark-muted">Operational status across {services.length} services</p>
        </div>
      </div>

      <div className="p-5">
        {/* Overall ring */}
        <div className="flex items-center justify-center mb-6">
          <div className="relative w-28 h-28">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="40" fill="none" stroke="#E2E8F0" strokeWidth="10" />
              <motion.circle
                cx="50" cy="50" r="40"
                fill="none"
                stroke={healthColor(overallHealth)}
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={`${2 * Math.PI * 40}`}
                initial={{ strokeDashoffset: 2 * Math.PI * 40 }}
                animate={{ strokeDashoffset: 2 * Math.PI * 40 * (1 - overallHealth / 100) }}
                transition={{ duration: 1.2, ease: 'easeOut' }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className={`text-2xl font-bold ${healthText(overallHealth)}`}>{overallHealth}%</span>
              <span className="text-xs text-light-muted dark:text-dark-muted">health</span>
            </div>
          </div>
        </div>

        {/* Per-service bars */}
        <div className="space-y-3">
          {services.map(service => {
            const h = calcHealth(service.name);
            const activeInc = incidents.filter(i => i.service_name === service.name && i.status === 'active').length;
            return (
              <motion.div
                key={service.name}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
              >
                <div className="flex items-center gap-2 mb-1">
                  {statusIcon(h)}
                  <span className="text-sm font-medium text-light-text dark:text-dark-text flex-1 truncate">
                    {service.name}
                  </span>
                  {/* Dependency count */}
                  {service.dependencies?.length > 0 && (
                    <span className="flex items-center gap-0.5 text-xs text-light-muted dark:text-dark-muted">
                      <GitBranch className="w-3 h-3" />
                      {service.dependencies.length}
                    </span>
                  )}
                  {/* On-call count */}
                  {service.on_call?.length > 0 && (
                    <span className="flex items-center gap-0.5 text-xs text-light-muted dark:text-dark-muted">
                      <Users className="w-3 h-3" />
                      {service.on_call.length}
                    </span>
                  )}
                  {activeInc > 0 && (
                    <span className="text-xs px-1.5 py-0.5 bg-severity-critical/15 text-severity-critical rounded-full font-medium">
                      {activeInc} active
                    </span>
                  )}
                  <span className={`text-xs font-semibold ${healthText(h)} w-9 text-right`}>{h}%</span>
                </div>
                <div className="h-1.5 bg-light-border dark:bg-dark-border rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${h}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                    className={`h-full rounded-full ${healthBg(h)}`}
                  />
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Summary row */}
        {services.length > 0 && (
          <div className="mt-5 grid grid-cols-2 gap-3">
            <div className="flex items-center justify-between p-3 bg-brand-success/8 rounded-xl border border-brand-success/20">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-brand-success" />
                <span className="text-xs text-light-text dark:text-dark-text">Healthy</span>
              </div>
              <span className="text-sm font-bold text-brand-success">
                {services.filter(s => calcHealth(s.name) >= 95).length}
              </span>
            </div>
            <div className="flex items-center justify-between p-3 bg-severity-critical/8 rounded-xl border border-severity-critical/20">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-severity-critical" />
                <span className="text-xs text-light-text dark:text-dark-text">Degraded</span>
              </div>
              <span className="text-sm font-bold text-severity-critical">
                {services.filter(s => calcHealth(s.name) < 95).length}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
