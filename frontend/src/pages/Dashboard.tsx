import { useEffect, useState } from 'react';
import { ServiceGraph } from '../components/ServiceGraph';
import { IncidentList } from '../components/IncidentList';
import { Stats } from '../components/Stats';
import { DeclareIncidentModal } from '../components/DeclareIncidentModal';
import { ActivityFeed } from '../components/ActivityFeed';
import { getIncidents, getServices, seedServices, type Incident, type Service } from '../utils/api';
import { PlusCircle, Database, RefreshCw } from 'lucide-react';

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [ws, setWs] = useState<WebSocket | null>(null);

  // WebSocket connection
  useEffect(() => {
    const websocket = new WebSocket('ws://localhost:8000/ws/incidents');
    setWs(websocket);
    return () => websocket.close();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [incidentsRes, servicesRes] = await Promise.all([
        getIncidents(),
        getServices(),
      ]);
      setIncidents(incidentsRes.incidents || []);
      setServices(servicesRes.services || []);
    } catch (err) {
      setError('Failed to fetch data. Make sure the backend is running.');
      console.error('Error fetching data:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSeedServices = async () => {
    try {
      setSeeding(true);
      await seedServices();
      await fetchData();
    } catch (err) {
      console.error('Error seeding services:', err);
    } finally {
      setSeeding(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleIncidentCreated = () => {
    fetchData();
  };

  const hasServices = services.length > 0;

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500 mx-auto"></div>
          <p className="mt-4 text-gray-500 dark:text-dark-muted">Loading AEGIS PRO...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-dark-text">Dashboard</h1>
          <p className="text-gray-500 dark:text-dark-muted">Monitor and manage incidents across your services</p>
        </div>
        <div className="flex gap-2">
          {!hasServices && (
            <button
              onClick={handleSeedServices}
              disabled={seeding}
              className="flex items-center gap-2 px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg transition shadow-md"
            >
              {seeding ? (
                <RefreshCw className="w-5 h-5 animate-spin" />
              ) : (
                <Database className="w-5 h-5" />
              )}
              {seeding ? 'Seeding...' : 'Seed Services'}
            </button>
          )}
          <button
            onClick={() => setIsModalOpen(true)}
            disabled={!hasServices}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition shadow-md ${
              hasServices 
                ? 'bg-primary-500 hover:bg-primary-600 text-white' 
                : 'bg-gray-300 text-gray-500 cursor-not-allowed'
            }`}
          >
            <PlusCircle className="w-5 h-5" />
            Declare Incident
          </button>
        </div>
      </div>

      {!hasServices && (
        <div className="bg-yellow-50 dark:bg-yellow-950/20 border border-yellow-200 dark:border-yellow-800 rounded-xl p-6 text-center">
          <Database className="w-12 h-12 text-yellow-500 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-yellow-800 dark:text-yellow-400">No Services Found</h3>
          <p className="text-yellow-700 dark:text-yellow-500 mt-1">
            Click "Seed Services" to populate the service catalog with demo data.
          </p>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
          <p className="text-red-600">{error}</p>
          <button
            onClick={fetchData}
            className="mt-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
          >
            Retry
          </button>
        </div>
      )}

      {hasServices && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Stats incidents={incidents} />
          </div>

          {/* Main Grid: Graph + Incident List */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2">
              <ServiceGraph services={services} incidents={incidents} />
            </div>
            <div className="lg:col-span-1">
              <IncidentList incidents={incidents} />
            </div>
          </div>

          {/* Activity Feed - NEW SECTION */}
          <div className="mt-8">
            <ActivityFeed websocket={ws} />
          </div>
        </>
      )}

      <DeclareIncidentModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={handleIncidentCreated}
        services={services}
      />
    </div>
  );
}
