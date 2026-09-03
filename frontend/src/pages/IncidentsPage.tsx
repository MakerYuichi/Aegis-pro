import { useState, useEffect } from 'react';
import { IncidentList } from '../components/IncidentList';
import { getIncidents, type Incident } from '../utils/api';
import { RefreshCw } from 'lucide-react';

export function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading incidents...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">Incidents</h1>
          <p className="text-light-muted dark:text-dark-muted">View and manage all incidents</p>
        </div>
        <button
          onClick={fetchIncidents}
          className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-brand-danger/10 border border-brand-danger/20 rounded-xl p-4 text-center">
          <p className="text-brand-danger">{error}</p>
        </div>
      )}

      <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
        <IncidentList incidents={incidents} />
      </div>
    </div>
  );
}