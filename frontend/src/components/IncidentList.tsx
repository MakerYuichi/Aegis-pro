import { Link } from 'react-router-dom';
import { useState } from 'react';
import { type Incident } from '../utils/api';
import { ChevronRight, Search, CheckCircle, Layers } from 'lucide-react';
import { motion } from 'framer-motion';

interface IncidentListProps {
  incidents: Incident[];
}

type FilterType = 'all' | 'P0' | 'P1' | 'P2' | 'active' | 'resolved';

export function IncidentList({ incidents }: IncidentListProps) {
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

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-light-text dark:text-dark-text">Recent Incidents</h3>
        <span className="text-xs text-light-muted dark:text-dark-muted">{filteredIncidents.length} total</span>
      </div>

      {/* Search and Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
          <input
            type="text"
            placeholder="Search incidents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-sm focus:ring-2 focus:ring-brand-primary focus:border-transparent text-light-text dark:text-dark-text"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto">
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

      <div className="space-y-2 max-h-96 overflow-y-auto custom-scrollbar">
        {filteredIncidents.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-12"
          >
            <CheckCircle className="w-12 h-12 text-brand-success mx-auto mb-3" />
            <p className="text-light-muted dark:text-dark-muted">No incidents found</p>
            <p className="text-light-muted dark:text-dark-muted text-sm mt-1">Everything is healthy! 🎉</p>
          </motion.div>
        ) : (
          filteredIncidents.slice(0, 20).map((incident, index) => {
            const affectedCount = incident.affected_services?.length || 0;
            const confidence = Math.round(incident.confidence_score * 100);
            
            return (
              <motion.div
                key={incident.incident_id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
              >
                <Link
                  to={`/incident/${incident.incident_id}`}
                  className="block border border-light-border dark:border-dark-border rounded-lg p-4 hover:bg-light-surface dark:hover:bg-dark-surface hover:border-brand-primary/40 hover:shadow-md transition group space-y-2"
                >
                  {/* Header: Severity, Service, Status */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${severityColors[incident.severity] ?? 'bg-light-surface dark:bg-dark-surface text-light-text dark:text-dark-text border-light-border dark:border-dark-border'}`}>
                        {incident.severity}
                      </span>
                      <span className="text-sm font-semibold text-light-text dark:text-dark-text">{incident.service_name}</span>
                      {incident.status === 'active' && (
                        <span className="flex items-center gap-1 px-2 py-0.5 bg-severity-critical/10 border border-severity-critical/20 rounded-full">
                          <span className="w-2 h-2 rounded-full bg-severity-critical animate-pulse"></span>
                          <span className="text-xs font-semibold text-severity-critical">active</span>
                        </span>
                      )}
                    </div>
                    <ChevronRight className="w-4 h-4 text-light-muted dark:text-dark-muted group-hover:text-brand-primary transition flex-shrink-0" />
                  </div>

                  {/* Title */}
                  <p className="text-sm font-medium text-light-text dark:text-dark-text line-clamp-1">{incident.title}</p>

                  {/* Incident ID */}
                  <p className="text-xs text-light-muted dark:text-dark-muted font-mono">{incident.incident_id}</p>

                  {/* Metadata Row: Confidence, Affected Services, Date */}
                  <div className="flex items-center gap-3 flex-wrap pt-1">
                    {/* Confidence Score */}
                    <div className="flex items-center gap-1.5 text-xs px-2 py-1 bg-light-surface/50 dark:bg-dark-surface/50 rounded">
                      <div className="w-4 h-4 rounded-full bg-gradient-to-r from-brand-primary to-brand-secondary flex items-center justify-center text-white font-bold text-xs">
                        {confidence > 0 ? '✓' : '?'}
                      </div>
                      <span className="text-light-muted dark:text-dark-muted">{confidence}%</span>
                    </div>

                    {/* Affected Services */}
                    {affectedCount > 0 && (
                      <div className="flex items-center gap-1.5 text-xs px-2 py-1 bg-light-surface/50 dark:bg-dark-surface/50 rounded">
                        <Layers className="w-3.5 h-3.5 text-brand-warning" />
                        <span className="text-light-muted dark:text-dark-muted">{affectedCount} affected</span>
                      </div>
                    )}

                    {/* Date */}
                    <div className="ml-auto text-xs text-light-muted dark:text-dark-muted">
                      {new Date(incident.declared_at).toLocaleDateString()} {new Date(incident.declared_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                </Link>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
