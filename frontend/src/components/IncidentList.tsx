import { Link } from 'react-router-dom';
import { useState } from 'react';
import { type Incident } from '../utils/api';
import { ChevronRight, Search, CheckCircle } from 'lucide-react';
import { motion } from 'framer-motion';

interface IncidentListProps {
  incidents: Incident[];
}

type FilterType = 'all' | 'P0' | 'P1' | 'P2' | 'active' | 'resolved';

export function IncidentList({ incidents }: IncidentListProps) {
  const [filter, setFilter] = useState<FilterType>('all');
  const [search, setSearch] = useState('');

  const severityColors: Record<string, string> = {
    P0: 'border-severity-critical bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-400',
    P1: 'border-severity-high bg-orange-50 dark:bg-orange-950/20 text-orange-700 dark:text-orange-400',
    P2: 'border-severity-medium bg-yellow-50 dark:bg-yellow-950/20 text-yellow-700 dark:text-yellow-400',
  };

  const filters = [
    { label: 'All', value: 'all' },
    { label: 'P0', value: 'P0' },
    { label: 'P1', value: 'P1' },
    { label: 'P2', value: 'P2' },
    { label: 'Active', value: 'active' },
    { label: 'Resolved', value: 'resolved' },
  ];

  const filteredIncidents = incidents.filter((incident) => {
    if (filter === 'all') return true;
    if (filter === 'active') return incident.status === 'active';
    if (filter === 'resolved') return incident.status === 'resolved';
    return incident.severity === filter;
  }).filter((incident) => {
    if (!search) return true;
    const query = search.toLowerCase();
    return incident.title.toLowerCase().includes(query) ||
           incident.service_name.toLowerCase().includes(query) ||
           incident.incident_id.toLowerCase().includes(query);
  });

  return (
    <div className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold dark:text-dark-text">Recent Incidents</h3>
        <span className="text-xs text-gray-500 dark:text-dark-muted">{filteredIncidents.length} total</span>
      </div>

      {/* Search and Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search incidents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-3 py-2 border border-gray-200 dark:border-dark-border rounded-lg bg-white dark:bg-dark-bg text-sm focus:ring-2 focus:ring-primary-500 focus:border-transparent dark:text-dark-text"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto">
          {filters.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value as FilterType)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition whitespace-nowrap ${
                filter === f.value
                  ? 'bg-primary-500 text-white'
                  : 'bg-gray-100 dark:bg-dark-border text-gray-600 dark:text-dark-muted hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2 max-h-96 overflow-y-auto">
        {filteredIncidents.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-12"
          >
            <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-dark-muted">No incidents found</p>
            <p className="text-gray-400 dark:text-dark-muted text-sm mt-1">Everything is healthy! 🎉</p>
          </motion.div>
        ) : (
          filteredIncidents.slice(0, 20).map((incident, index) => (
            <motion.div
              key={incident.incident_id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <Link
                to={`/incident/${incident.incident_id}`}
                className="block border border-gray-200 dark:border-dark-border rounded-lg p-3 hover:bg-gray-50 dark:hover:bg-dark-bg/50 hover:border-primary-300 dark:hover:border-primary-700 transition group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${severityColors[incident.severity] || 'bg-gray-100 text-gray-800'}`}>
                      {incident.severity}
                    </span>
                    <span className="text-sm font-medium dark:text-dark-text">{incident.service_name}</span>
                    {incident.status === 'active' && (
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-severity-critical animate-pulse"></span>
                        <span className="text-xs text-severity-critical">active</span>
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 dark:text-dark-muted">
                      {new Date(incident.declared_at).toLocaleDateString()}
                    </span>
                    <ChevronRight className="w-4 h-4 text-gray-400 group-hover:text-primary-500 transition" />
                  </div>
                </div>
                <p className="text-sm text-gray-600 dark:text-dark-muted mt-1 truncate">{incident.title}</p>
              </Link>
            </motion.div>
          ))
        )}
      </div>
    </div>
  );
}