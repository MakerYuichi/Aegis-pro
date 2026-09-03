import { useState, useEffect } from 'react';
import { OnCallRotation } from '../components/OnCallRotation';
import { getServices, type Service } from '../utils/api';
import { RefreshCw } from 'lucide-react';

export function OnCallPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await getServices();
      setServices(response.services || []);
    } catch (err) {
      setError('Failed to fetch on-call information');
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
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading on-call information...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">On-Call Schedule</h1>
          <p className="text-light-muted dark:text-dark-muted">View current on-call rotations and schedules</p>
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

      <div className="max-w-2xl">
        <OnCallRotation services={services} />
      </div>
    </div>
  );
}