import { useState, useEffect } from 'react';
import { ServiceGraph } from '../components/ServiceGraph';
import { ServiceHealthRing } from '../components/ServiceHealthRing';
import { getServices, type Service } from '../utils/api';
import { RefreshCw } from 'lucide-react';
import { type Incident } from '../utils/api';

export function ServicesPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const servicesRes = await getServices();
      setServices(servicesRes.services || []);
      // Mock incidents for service health
      setIncidents([]);
    } catch (err) {
      setError('Failed to fetch services');
      console.error('Error fetching services:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-primary animate-spin mx-auto" />
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading services...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">Services</h1>
          <p className="text-light-muted dark:text-dark-muted">Monitor service health and dependencies</p>
        </div>
        <button
          onClick={fetchData}
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border shadow-lg p-6">
          <ServiceGraph services={services} incidents={incidents} />
        </div>
        <div>
          <ServiceHealthRing services={services} incidents={incidents} />
        </div>
      </div>
    </div>
  );
}