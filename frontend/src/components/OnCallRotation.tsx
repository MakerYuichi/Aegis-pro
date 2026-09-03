import { Users, Clock, RotateCcw, Shield, Mail } from 'lucide-react';
import { motion } from 'framer-motion';
import { type Service } from '../utils/api';

interface OnCallRotationProps {
  services: Service[];
}

export function OnCallRotation({ services }: OnCallRotationProps) {
  const getNextRotationTime = () => {
    const now = new Date();
    const nextRotation = new Date(now.getTime() + 4 * 60 * 60 * 1000); // 4 hours from now
    const diff = nextRotation.getTime() - now.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    return `${hours}h ${minutes}m`;
  };

  const criticalServices = services.filter(s => s.is_critical);
  const primaryService = criticalServices[0] || services[0];

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      <div className="p-6 border-b border-light-border dark:border-dark-border">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-brand-primary/10 rounded-lg">
            <Users className="w-5 h-5 text-brand-primary" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-light-text dark:text-dark-text">On-Call Rotation</h3>
            <p className="text-sm text-light-muted dark:text-dark-muted">Current duty roster</p>
          </div>
        </div>
      </div>

      <div className="p-6 space-y-4">
        {/* Primary Service */}
        {primaryService && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-brand-success/10 rounded-xl p-4 border border-brand-success/20"
          >
            <div className="flex items-center gap-2 mb-3">
              <Shield className="w-4 h-4 text-brand-success" />
              <span className="text-xs font-medium text-brand-success uppercase tracking-wider">Primary</span>
              <span className="text-xs text-light-muted dark:text-dark-muted ml-auto">{primaryService.name}</span>
            </div>
            <div className="space-y-2">
              {primaryService.on_call.slice(0, 3).map((person, index) => (
                <div key={person} className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                    index === 0 ? 'bg-brand-success/20 text-brand-success border border-brand-success/30' :
                    index === 1 ? 'bg-brand-warning/20 text-brand-warning border border-brand-warning/30' :
                    'bg-brand-primary/20 text-brand-primary border border-brand-primary/30'
                  }`}>
                    {person.charAt(1)}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-light-text dark:text-dark-text">{person}</p>
                    <p className="text-xs text-light-muted dark:text-dark-muted">
                      {index === 0 ? 'Primary On-Call' : index === 1 ? 'Secondary' : 'Tertiary'}
                    </p>
                  </div>
                  <button className="p-1.5 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors">
                    <Mail className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                  </button>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Next Rotation */}
        <div className="bg-light-surface dark:bg-dark-surface rounded-xl p-4 border border-light-border dark:border-dark-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-brand-primary" />
              <span className="text-sm text-light-muted dark:text-dark-muted">Next rotation in</span>
            </div>
            <div className="flex items-center gap-2">
              <RotateCcw className="w-4 h-4 text-brand-primary animate-spin" style={{ animationDuration: '3s' }} />
              <span className="text-sm font-medium text-light-text dark:text-dark-text">{getNextRotationTime()}</span>
            </div>
          </div>
        </div>

        {/* Other Critical Services */}
        {criticalServices.slice(1).map((service) => (
          <motion.div
            key={service.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-light-surface dark:bg-dark-surface rounded-xl p-4 border border-light-border dark:border-dark-border"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-light-text dark:text-dark-text">{service.name}</span>
              <Shield className="w-4 h-4 text-brand-warning" />
            </div>
            <div className="flex flex-wrap gap-2">
              {service.on_call.slice(0, 2).map((person) => (
                <span key={person} className="text-xs bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text px-2 py-1 rounded-full">
                  {person}
                </span>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}