import { useEffect, useState } from 'react';
import { ServiceGraph } from '../components/ServiceGraph';
import { Stats } from '../components/Stats';
import { DeclareIncidentModal } from '../components/DeclareIncidentModal';
import { ActivityFeed } from '../components/ActivityFeed';
import { LiveIncidentTimeline } from '../components/LiveIncidentTimeline';
import { ServiceHealthRing } from '../components/ServiceHealthRing';
import { IncidentSidePanel } from '../components/IncidentSidePanel';
import { OnCallRotation } from '../components/OnCallRotation';
import { getIncidents, getServices, seedServices, type Incident, type Service } from '../utils/api';
import { PlusCircle, Database, RefreshCw, Zap } from 'lucide-react';

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState<string | null>(null);
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

  const handleIncidentClick = (incident: Incident) => {
    setSelectedIncident(incident.incident_id);
  };

  const hasServices = services.length > 0;

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-center">
          <div className="relative">
            <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-brand-primary"></div>
            <Zap className="w-6 h-6 text-brand-primary absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2" />
          </div>
          <p className="mt-4 text-light-muted dark:text-dark-muted">Loading AEGIS PRO v2.0...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-light-text dark:text-dark-text">
            Dashboard
          </h1>
          <p className="text-light-muted dark:text-dark-muted">Monitor and manage incidents across your services</p>
        </div>
        <div className="flex gap-2">
          {!hasServices && (
            <button
              onClick={handleSeedServices}
              disabled={seeding}
              className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition shadow-md"
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
                ? 'bg-brand-primary text-white hover:bg-brand-primary/90' 
                : 'bg-light-border dark:bg-dark-border text-light-muted dark:text-dark-muted cursor-not-allowed'
            }`}
          >
            <PlusCircle className="w-5 h-5" />
            Declare Incident
          </button>
        </div>
      </div>

      {!hasServices && (
        <div className="bg-brand-warning/10 border border-brand-warning/30 rounded-2xl p-8 text-center">
          <Database className="w-16 h-16 text-brand-warning mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-brand-warning">No Services Found</h3>
          <p className="text-light-muted dark:text-dark-muted mt-2">
            Click "Seed Services" to populate the service catalog with demo data.
          </p>
        </div>
      )}

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-6 text-center">
          <p className="text-severity-critical">{error}</p>
          <button
            onClick={fetchData}
            className="mt-4 px-6 py-2 bg-severity-critical text-white rounded-lg hover:bg-severity-critical/90 transition"
          >
            Retry
          </button>
        </div>
      )}

      {hasServices && (
        <div className="space-y-6">
          {/* Top Row - Stats */}
          <Stats incidents={incidents} />

          {/* Middle Row - Live Monitoring */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Live Incident Timeline */}
            <LiveIncidentTimeline 
              incidents={incidents} 
              onIncidentClick={handleIncidentClick}
            />

            {/* Activity Feed */}
            <ActivityFeed websocket={ws} initialIncidents={incidents} />
          </div>

          {/* Bottom Row - Service Overview */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Service Dependency Graph - takes 2 cols */}
            <div className="lg:col-span-2">
              <ServiceGraph services={services} incidents={incidents} />
            </div>

            {/* Right Widgets - takes 1 col */}
            <div className="space-y-6">
              {/* Service Health Ring */}
              <ServiceHealthRing services={services} incidents={incidents} />

              {/* On-Call Rotation */}
              <OnCallRotation services={services} />
            </div>
          </div>
        </div>
      )}

      <DeclareIncidentModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={handleIncidentCreated}
        services={services}
      />

      <IncidentSidePanel
        incidentId={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />
    </div>
  );
}
