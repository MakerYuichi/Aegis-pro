import { Link } from 'react-router-dom';
import { useState } from 'react';
import { type Incident } from '../utils/api';
import { ChevronRight, Search, CheckCircle, Layers, AlertTriangle } from 'lucide-react';
import { motion } from 'framer-motion';

interface IncidentListDirectProps {
  incidents: Incident[];
}

type FilterType = 'all' | 'P0' | 'P1' | 'P2' | 'active' | 'resolved';

export function IncidentListDirect({ incidents }: IncidentListDirectProps) {
  const [filter, setFilter] = useState<FilterType>('all');
  const [search, setSearch] = useState('');

  const severityColors: Record<string, string> = {
    P0: 'border-severity-critical bg-severity-critical/10 text-severity-critical',
    P1: 'border-severity-high bg-severity-high/10 text-severity-high',
    P2: 'border-severity-medium bg-severity-medium/10 text-severity-medium',
  };

  const filters: { label: string; value: FilterType }[] = [
    { label: 'All', value: 'all' },
    { label: 'P0', value: 'P0' },
    { label: 'P1', value: 'P1' },
    { label: 'P2', value: 'P2' },
    { label: 'Active', value: 'active' },
    { label: 'Resolved', value: 'resolved' },
  ];

  const filteredIncidents = incidents
    .filter((incident) => {
      if (filter === 'all') return true;
      if (filter === 'active') return incident.status === 'active';
      if (filter === 'resolved') return incident.status !== 'active';
      return incident.severity === filter;
    })
    .filter((incident) => {
      if (!search) return true;
      const query = search.toLowerCase();
      return (
        incident.title.toLowerCase().includes(query) ||
        incident.service_name.toLowerCase().includes(query) ||
        incident.incident_id.toLowerCase().includes(query)
      );
    });

  const getRelativeTime = (dateString: string) => {
    const now = new Date();
    const past = new Date(dateString);
    const diffMs = now.getTime() - past.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <div className="space-y-4">
      {/* Search and Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
          <input
            type="text"
            placeholder="Search incidents by ID, title, or service..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-3 py-2.5 border border-light-border dark:border-dark-border rounded-xl bg-light-bg dark:bg-dark-bg text-sm focus:ring-2 focus:ring-brand-primary focus:border-transparent text-light-text dark:text-dark-text"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto pb-1">
          {filters.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition whitespace-nowrap ${
                filter === f.value
                  ? 'bg-brand-primary text-white'
                  : 'bg-light-surface dark:bg-dark-surface text-light-muted dark:text-dark-muted hover:bg-light-border dark:hover:bg-dark-border'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {filteredIncidents.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center py-16"
        >
          <CheckCircle className="w-16 h-16 text-brand-success mx-auto mb-4" />
          <p className="text-lg font-semibold text-light-text dark:text-dark-text">No incidents found</p>
          <p className="text-light-muted dark:text-dark-muted text-sm mt-1">Everything is healthy! 🎉</p>
        </motion.div>
      ) : (
        <div className="space-y-3">
          {filteredIncidents.map((incident, index) => {
            const affectedCount = incident.affected_services?.length || 0;
            const confidence = Math.round(incident.confidence_score * 100);
            const relativeTime = getRelativeTime(incident.declared_at);
            
            return (
              <motion.div
                key={incident.incident_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
              >
                <Link
                  to={`/incident/${incident.incident_id}`}
                  className="block bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-5 hover:border-brand-primary/40 hover:shadow-md hover:bg-light-surface/50 dark:hover:bg-dark-surface/50 transition group"
                >
                  {/* Header: Severity, Service, Status */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold border ${severityColors[incident.severity] ?? 'bg-light-surface dark:bg-dark-surface text-light-text dark:text-dark-text border-light-border dark:border-dark-border'}`}>
                        {incident.severity}
                      </span>
                      <span className="text-sm font-semibold text-light-text dark:text-dark-text">{incident.service_name}</span>
                      {incident.status === 'active' && (
                        <span className="flex items-center gap-1.5 px-2.5 py-0.5 bg-severity-critical/10 border border-severity-critical/20 rounded-full">
                          <span className="w-2 h-2 rounded-full bg-severity-critical animate-pulse"></span>
                          <span className="text-xs font-semibold text-severity-critical">active</span>
                        </span>
                      )}
                    </div>
                    <ChevronRight className="w-4 h-4 text-light-muted dark:text-dark-muted group-hover:text-brand-primary transition flex-shrink-0" />
                  </div>

                  {/* Title */}
                  <h3 className="text-base font-medium text-light-text dark:text-dark-text line-clamp-1 mb-1">
                    {incident.title}
                  </h3>

                  {/* Incident ID */}
                  <p className="text-xs text-light-muted dark:text-dark-muted font-mono mb-2">{incident.incident_id}</p>

                  {/* Metadata Row: Confidence, Affected Services, Date */}
                  <div className="flex items-center gap-4 flex-wrap pt-1 border-t border-light-border/50 dark:border-dark-border/50 pt-2">
                    {/* Confidence Score */}
                    {confidence > 0 && (
                      <div className="flex items-center gap-1.5 text-xs">
                        <div className={`w-5 h-5 rounded-full flex items-center justify-center text-white font-bold text-xs ${
                          confidence >= 80 ? 'bg-brand-success' :
                          confidence >= 60 ? 'bg-brand-warning' : 'bg-severity-critical'
                        }`}>
                          ✓
                        </div>
                        <span className="text-light-muted dark:text-dark-muted">{confidence}% confidence</span>
                      </div>
                    )}

                    {/* Affected Services */}
                    {affectedCount > 0 && (
                      <div className="flex items-center gap-1.5 text-xs text-light-muted dark:text-dark-muted">
                        <Layers className="w-3.5 h-3.5 text-brand-warning" />
                        <span>{affectedCount} services affected</span>
                      </div>
                    )}

                    {/* Time */}
                    <div className="text-xs text-light-muted dark:text-dark-muted ml-auto">
                      {relativeTime}
                    </div>
                  </div>

                  {/* Optional: Root Cause Preview */}
                  {incident.root_cause && (
                    <p className="text-xs text-light-muted dark:text-dark-muted mt-2 line-clamp-2 opacity-75">
                      {incident.root_cause.slice(0, 150)}...
                    </p>
                  )}
                </Link>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
