import { Clock, AlertTriangle, AlertCircle, Info, ChevronRight } from 'lucide-react';
import { motion } from 'framer-motion';
import { type Incident } from '../utils/api';

interface LiveIncidentTimelineProps {
  incidents: Incident[];
  onIncidentClick?: (incident: Incident) => void;
}

export function LiveIncidentTimeline({ incidents, onIncidentClick }: LiveIncidentTimelineProps) {
  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'P0': return <AlertTriangle className="w-4 h-4 text-severity-critical" />;
      case 'P1': return <AlertCircle className="w-4 h-4 text-severity-high" />;
      case 'P2': return <Info className="w-4 h-4 text-severity-medium" />;
      default: return <AlertCircle className="w-4 h-4 text-light-muted dark:text-dark-muted" />;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'P0': return 'border-severity-critical/30 bg-severity-critical/10 hover:bg-severity-critical/20';
      case 'P1': return 'border-severity-high/30 bg-severity-high/10 hover:bg-severity-high/20';
      case 'P2': return 'border-severity-medium/30 bg-severity-medium/10 hover:bg-severity-medium/20';
      default: return 'border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface hover:bg-light-border dark:hover:bg-dark-border';
    }
  };

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case 'P0': return 'bg-severity-critical/20 text-severity-critical border-severity-critical/30';
      case 'P1': return 'bg-severity-high/20 text-severity-high border-severity-high/30';
      case 'P2': return 'bg-severity-medium/20 text-severity-medium border-severity-medium/30';
      default: return 'bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted border-light-border dark:border-dark-border';
    }
  };

  const formatTimeAgo = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} min ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  const sortedIncidents = [...incidents].sort((a, b) => 
    new Date(b.declared_at).getTime() - new Date(a.declared_at).getTime()
  ).slice(0, 10);

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg overflow-hidden">
      <div className="p-6 border-b border-light-border dark:border-dark-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-brand-warning/10 rounded-lg">
              <Clock className="w-5 h-5 text-brand-warning" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-light-text dark:text-dark-text">Incident Timeline</h3>
              <p className="text-sm text-light-muted dark:text-dark-muted">Last 24 hours</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-light-muted dark:text-dark-muted">Live</span>
            <span className="w-2 h-2 rounded-full bg-brand-success animate-pulse"></span>
          </div>
        </div>
      </div>

      <div className="p-4 space-y-2 max-h-96 overflow-y-auto custom-scrollbar">
        {sortedIncidents.length === 0 ? (
          <div className="text-center py-12">
            <Clock className="w-12 h-12 text-light-muted dark:text-dark-muted mx-auto mb-3" />
            <p className="text-light-muted dark:text-dark-muted">No incidents in the last 24 hours</p>
          </div>
        ) : (
          sortedIncidents.map((incident, index) => (
            <motion.div
              key={incident.incident_id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              onClick={() => onIncidentClick?.(incident)}
              className={`p-4 rounded-xl border transition-all duration-200 cursor-pointer group ${getSeverityColor(incident.severity)}`}
            >
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0">
                  {getSeverityIcon(incident.severity)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-light-text dark:text-dark-text truncate">
                      {incident.incident_id}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${getSeverityBadge(incident.severity)}`}>
                      {incident.severity}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-light-muted dark:text-dark-muted">
                    <span className="truncate">{incident.service_name}</span>
                    <span className="text-light-border dark:text-dark-border">•</span>
                    <span className="text-xs">{formatTimeAgo(incident.declared_at)}</span>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-light-muted dark:text-dark-muted group-hover:text-light-text dark:group-hover:text-dark-text transition-colors" />
              </div>
            </motion.div>
          ))
        )}
      </div>
    </div>
  );
}