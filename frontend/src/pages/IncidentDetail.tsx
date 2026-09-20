import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, RefreshCw, AlertTriangle } from 'lucide-react';
import { getIncident, type Incident } from '../utils/api';
import { IncidentView } from '../components/IncidentView';

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) fetchIncident(id);
  }, [id]);

  const fetchIncident = async (incidentId: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await getIncident(incidentId);
      setIncident(data);
    } catch (err) {
      setError('Incident not found');
      console.error('Error fetching incident:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading incident details...</p>
        </div>
      </div>
    );
  }

  if (error || !incident) {
    return (
      <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-8 text-center">
        <AlertTriangle className="w-12 h-12 text-severity-critical mx-auto mb-3" />
        <p className="text-severity-critical">{error || 'Incident not found'}</p>
        <Link to="/" className="mt-4 inline-block text-brand-primary hover:underline">
          ← Back to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="text-light-muted dark:text-dark-muted hover:text-brand-primary transition">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">Incident Details</h1>
          <p className="text-sm text-light-muted dark:text-dark-muted">{incident.incident_id}</p>
        </div>
      </div>
      <IncidentView
        incident={incident}
        onIncidentChange={() => id && fetchIncident(id)}
      />
    </div>
  );
}
