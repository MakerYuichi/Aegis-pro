import { Activity, CheckCircle, AlertTriangle, XCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import { type Service, type Incident } from '../utils/api';

interface ServiceHealthRingProps {
  services: Service[];
  incidents: Incident[];
}

export function ServiceHealthRing({ services, incidents }: ServiceHealthRingProps) {
  const calculateServiceHealth = (serviceName: string) => {
    const serviceIncidents = incidents.filter(i => i.service_name === serviceName && i.status === 'active');
    const totalIncidents = incidents.filter(i => i.service_name === serviceName).length;
    
    if (serviceIncidents.length === 0 && totalIncidents === 0) return 100;
    if (serviceIncidents.length > 0) return Math.max(0, 100 - (serviceIncidents.length * 20));
    return Math.max(0, 100 - (totalIncidents * 5));
  };

  const overallHealth = services.length > 0 
    ? Math.round(services.reduce((acc, service) => acc + calculateServiceHealth(service.name), 0) / services.length)
    : 100;

  const getServiceStatusIcon = (health: number) => {
    if (health >= 95) return <CheckCircle className="w-4 h-4 text-brand-success" />;
    if (health >= 80) return <Activity className="w-4 h-4 text-brand-warning" />;
    if (health >= 60) return <AlertTriangle className="w-4 h-4 text-severity-high" />;
    return <XCircle className="w-4 h-4 text-severity-critical" />;
  };

  const getHealthColor = (health: number) => {
    if (health >= 95) return 'bg-brand-success';
    if (health >= 80) return 'bg-brand-warning';
    if (health >= 60) return 'bg-severity-high';
    return 'bg-severity-critical';
  };

  const getHealthTextColor = (health: number) => {
    if (health >= 95) return 'text-brand-success';
    if (health >= 80) return 'text-brand-warning';
    if (health >= 60) return 'text-severity-high';
    return 'text-severity-critical';
  };

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      <div className="p-6 border-b border-light-border dark:border-dark-border">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-brand-success/10 rounded-lg">
            <Activity className="w-5 h-5 text-brand-success" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-light-text dark:text-dark-text">Service Health</h3>
            <p className="text-sm text-light-muted dark:text-dark-muted">Real-time operational status</p>
          </div>
        </div>
      </div>

      <div className="p-6">
        {/* Overall Health Ring */}
        <div className="flex items-center justify-center mb-8">
          <div className="relative">
            <div className="w-32 h-32 rounded-full border-8 border-light-border dark:border-dark-border flex items-center justify-center">
              <div className="text-center">
                <div className={`text-3xl font-bold ${getHealthTextColor(overallHealth)}`}>
                  {overallHealth}%
                </div>
                <div className="text-xs text-light-muted dark:text-dark-muted">Operational</div>
              </div>
            </div>
            <motion.div
              className="absolute inset-0 rounded-full border-8 border-transparent"
              style={{
                borderTopColor: overallHealth >= 95 ? '#10B981' : 
                               overallHealth >= 80 ? '#F59E0B' : 
                               overallHealth >= 60 ? '#EA580C' : '#DC2626',
                transform: 'rotate(-90deg)',
              }}
              initial={{ rotate: -90 }}
              animate={{ rotate: -90 + (overallHealth / 100) * 360 }}
              transition={{ duration: 1, ease: "easeOut" }}
            />
          </div>
        </div>

        {/* Individual Service Health */}
        <div className="space-y-4">
          {services.map((service) => {
            const health = calculateServiceHealth(service.name);
            return (
              <motion.div
                key={service.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-3"
              >
                <div className="flex-shrink-0">
                  {getServiceStatusIcon(health)}
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-light-text dark:text-dark-text">{service.name}</span>
                    <span className={`text-xs font-medium ${getHealthTextColor(health)}`}>
                      {health}%
                    </span>
                  </div>
                  <div className="h-2 bg-light-border dark:bg-dark-border rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${health}%` }}
                      transition={{ duration: 0.8, ease: "easeOut" }}
                      className={`h-full rounded-full ${getHealthColor(health)}`}
                    />
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}