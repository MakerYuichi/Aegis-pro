import { useState, useEffect } from 'react';
import { IncidentList } from '../components/IncidentList';
import { getIncidents, type Incident } from '../utils/api';
import { RefreshCw, Search, Filter, AlertTriangle, Layers, ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [sortBy, setSortBy] = useState<'recent' | 'severity' | 'confidence'>('recent');
  const [showFilters, setShowFilters] = useState(false);

  const fetchIncidents = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await getIncidents();
      setIncidents(response.incidents || []);
    } catch (err) {
      setError('Failed to fetch incidents');
      console.error('Error fetching incidents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIncidents();
  }, []);

  // Filter and sort
  const filtered = incidents.filter(inc => {
    if (filterSeverity !== 'all' && inc.severity !== filterSeverity) return false;
    if (filterStatus !== 'all' && inc.status !== filterStatus) return false;
    const q = searchTerm.toLowerCase();
    if (q && !inc.title?.toLowerCase().includes(q) && !inc.incident_id.toLowerCase().includes(q) && !inc.service_name.toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => {
    if (sortBy === 'recent') return new Date(b.declared_at).getTime() - new Date(a.declared_at).getTime();
    if (sortBy === 'severity') {
      const severityOrder = { 'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3 };
      return (severityOrder[a.severity as keyof typeof severityOrder] ?? 99) - (severityOrder[b.severity as keyof typeof severityOrder] ?? 99);
    }
    if (sortBy === 'confidence') return b.confidence_score - a.confidence_score;
    return 0;
  });

  const severityStats = {
    P0: incidents.filter(i => i.severity === 'P0').length,
    P1: incidents.filter(i => i.severity === 'P1').length,
    P2: incidents.filter(i => i.severity === 'P2').length,
  };

  const statusStats = {
    active: incidents.filter(i => i.status === 'active').length,
    resolved: incidents.filter(i => i.status === 'resolved').length,
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center space-y-4">
          <div className="relative w-16 h-16 mx-auto">
            <div className="absolute inset-0 animate-spin rounded-full border-4 border-transparent border-t-brand-primary border-r-brand-primary/40"></div>
            <AlertTriangle className="w-8 h-8 text-brand-warning absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2" />
          </div>
          <div>
            <p className="text-lg font-semibold text-light-text dark:text-dark-text">Loading incidents</p>
            <p className="text-sm text-light-muted dark:text-dark-muted">Fetching data from backend...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-4xl font-bold bg-gradient-to-r from-brand-primary to-brand-secondary bg-clip-text text-transparent">
              All Incidents
            </h1>
            <p className="text-light-muted dark:text-dark-muted">Manage and investigate incidents across your services</p>
          </div>
          <button
            onClick={fetchIncidents}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary text-white rounded-xl hover:bg-brand-primary/90 transition font-semibold text-sm shadow-lg self-start md:self-auto"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4 space-y-1"
          >
            <p className="text-xs font-semibold text-light-muted dark:text-dark-muted uppercase tracking-wide">Total</p>
            <p className="text-2xl font-bold text-light-text dark:text-dark-text">{incidents.length}</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="bg-light-card dark:bg-dark-card rounded-xl border border-severity-critical/20 p-4 space-y-1 bg-severity-critical/5"
          >
            <p className="text-xs font-semibold text-severity-critical uppercase tracking-wide">P0 — Critical</p>
            <p className="text-2xl font-bold text-severity-critical">{severityStats.P0}</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-light-card dark:bg-dark-card rounded-xl border border-severity-high/20 p-4 space-y-1 bg-severity-high/5"
          >
            <p className="text-xs font-semibold text-severity-high uppercase tracking-wide">P1 — High</p>
            <p className="text-2xl font-bold text-severity-high">{severityStats.P1}</p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="bg-light-card dark:bg-dark-card rounded-xl border border-brand-success/20 p-4 space-y-1 bg-brand-success/5"
          >
            <p className="text-xs font-semibold text-brand-success uppercase tracking-wide">Resolved</p>
            <p className="text-2xl font-bold text-brand-success">{statusStats.resolved}</p>
          </motion.div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="space-y-3">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="flex items-center justify-between w-full px-4 py-3 bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border hover:bg-light-surface dark:hover:bg-dark-surface transition"
        >
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-brand-primary" />
            <span className="font-semibold text-light-text dark:text-dark-text">Filters & Search</span>
          </div>
          <ChevronDown className={`w-4 h-4 text-light-muted dark:text-dark-muted transition ${showFilters ? 'rotate-180' : ''}`} />
        </button>

        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="bg-light-surface dark:bg-dark-surface rounded-xl border border-light-border dark:border-dark-border p-4 space-y-4">
                {/* Search */}
                <div>
                  <label className="text-sm font-semibold text-light-text dark:text-dark-text mb-2 block">Search</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
                    <input
                      type="text"
                      placeholder="Incident ID, title, or service…"
                      value={searchTerm}
                      onChange={e => setSearchTerm(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text text-sm focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                    />
                  </div>
                </div>

                {/* Filter Row */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="text-sm font-semibold text-light-text dark:text-dark-text mb-2 block">Severity</label>
                    <select
                      value={filterSeverity}
                      onChange={e => setFilterSeverity(e.target.value)}
                      className="w-full px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                    >
                      <option value="all">All Severity</option>
                      <option value="P0">P0 — Critical</option>
                      <option value="P1">P1 — High</option>
                      <option value="P2">P2 — Medium</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-sm font-semibold text-light-text dark:text-dark-text mb-2 block">Status</label>
                    <select
                      value={filterStatus}
                      onChange={e => setFilterStatus(e.target.value)}
                      className="w-full px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                    >
                      <option value="all">All Status</option>
                      <option value="active">Active</option>
                      <option value="resolved">Resolved</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-sm font-semibold text-light-text dark:text-dark-text mb-2 block">Sort By</label>
                    <select
                      value={sortBy}
                      onChange={e => setSortBy(e.target.value as any)}
                      className="w-full px-3 py-2.5 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                    >
                      <option value="recent">Most Recent</option>
                      <option value="severity">By Severity</option>
                      <option value="confidence">By Confidence</option>
                    </select>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Results */}
      {filtered.length === 0 ? (
        <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-14 text-center">
          <Layers className="w-14 h-14 text-light-muted dark:text-dark-muted mx-auto mb-4 opacity-50" />
          <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-1">No incidents found</h3>
          <p className="text-sm text-light-muted dark:text-dark-muted">Try adjusting your filters or search term</p>
        </div>
      ) : (
        <IncidentList incidents={filtered} />
      )}
    </div>
  );
}