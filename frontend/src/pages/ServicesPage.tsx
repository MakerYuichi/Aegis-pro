import { useState, useEffect } from 'react';
import { ServiceHealthRing } from '../components/ServiceHealthRing';
import { getServices, getIncidents, createService, deleteService, type Service, type Incident } from '../utils/api';
import { RefreshCw, Plus, Server, AlertTriangle, Activity, User, Edit, Trash2 } from 'lucide-react';
import { motion } from 'framer-motion';

export function ServicesPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddService, setShowAddService] = useState(false);
  const [newService, setNewService] = useState<Partial<Service>>({ is_critical: false, dependencies: [] });

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [servicesRes, incidentsRes] = await Promise.all([
        getServices(),
        getIncidents()
      ]);
      setServices(servicesRes.services || []);
      setIncidents(incidentsRes.incidents || []);
    } catch (err) {
      setError('Failed to fetch services');
      console.error('Error fetching services:', err);
    } finally {
      setLoading(false);
    }
  };

  const addService = async () => {
    if (newService.name && newService.repo_name) {
      try {
        await createService({
          name: newService.name,
          description: newService.description || '',
          repo_name: newService.repo_name,
          dependencies: newService.dependencies || [],
          is_critical: newService.is_critical || false,
        });
        setNewService({ is_critical: false, dependencies: [] });
        setShowAddService(false);
        await fetchData();
      } catch (err) {
        console.error('Error adding service:', err);
        setError('Failed to add service');
      }
    }
  };

  const handleDeleteService = async (name: string) => {
    if (!confirm(`Delete service "${name}"?`)) return;
    try {
      await deleteService(name);
      await fetchData();
    } catch (err) {
      console.error('Error deleting service:', err);
      setError('Failed to delete service');
    }
  };

  const getServiceHealth = (serviceName: string) => {
    const serviceIncidents = incidents.filter(i => i.service_name === serviceName);
    const activeIncidents = serviceIncidents.filter(i => i.status === 'active');
    const totalIncidents = serviceIncidents.length;
    
    // Calculate real metrics from incident data
    const errorRate = totalIncidents > 0 ? Math.round((activeIncidents.length / totalIncidents) * 100) : 0;
    const avgResponseTime = serviceIncidents.length > 0 ? 
      Math.round(serviceIncidents.reduce((sum, i) => {
        const created = new Date(i.declared_at).getTime();
        const resolved = i.resolved_at ? new Date(i.resolved_at).getTime() : Date.now();
        return sum + ((resolved - created) / (1000 * 60)); // Convert to minutes
      }, 0) / serviceIncidents.length) : 0;
    
    const uptime = activeIncidents.length === 0 ? 99.9 : Math.max(0, 100 - (activeIncidents.length * 2)); // More realistic calculation
    
    return {
      status: activeIncidents.length > 0 ? 'degraded' : 'healthy',
      activeIncidents: activeIncidents.length,
      totalIncidents: totalIncidents,
      errorRate: errorRate,
      uptime: uptime,
      avgResponseTime: avgResponseTime
    };
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
        <div className="flex gap-2">
          <button
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2 bg-light-surface dark:bg-dark-surface border border-light-border dark:border-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border dark:hover:bg-dark-border transition"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            onClick={() => setShowAddService(true)}
            className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition shadow-md"
          >
            <Plus className="w-4 h-4" />
            Add Service
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-center">
          <p className="text-severity-critical">{error}</p>
        </div>
      )}

      {showAddService && (
        <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm">
          <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">Add New Service</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <input
              type="text"
              placeholder="Service Name"
              value={newService.name || ''}
              onChange={(e) => setNewService({ ...newService, name: e.target.value })}
              className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
            />
            <input
              type="text"
              placeholder="GitHub Repo Name"
              value={newService.repo_name || ''}
              onChange={(e) => setNewService({ ...newService, repo_name: e.target.value })}
              className="px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
            />
            <input
              type="text"
              placeholder="Description"
              value={newService.description || ''}
              onChange={(e) => setNewService({ ...newService, description: e.target.value })}
              className="md:col-span-2 px-4 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text"
            />
            <label className="flex items-center gap-2 text-light-text dark:text-dark-text">
              <input
                type="checkbox"
                checked={newService.is_critical || false}
                onChange={(e) => setNewService({ ...newService, is_critical: e.target.checked })}
                className="w-4 h-4"
              />
              Critical Service
            </label>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={addService}
              className="flex items-center gap-2 px-4 py-2 bg-brand-success text-white rounded-lg hover:bg-brand-success/90 transition"
            >
              <Plus className="w-4 h-4" />
              Add Service
            </button>
            <button
              onClick={() => setShowAddService(false)}
              className="px-4 py-2 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-border/80 dark:hover:bg-dark-border/80 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Service List */}
        <div className="lg:col-span-2 space-y-4">
          {services.map((service) => {
            const health = getServiceHealth(service.name);
            return (
              <motion.div
                key={service.name}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                      health.status === 'healthy' ? 'bg-brand-success/20' : 'bg-severity-critical/20'
                    }`}>
                      <Server className={`w-6 h-6 ${health.status === 'healthy' ? 'text-brand-success' : 'text-severity-critical'}`} />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-light-text dark:text-dark-text">{service.name}</h3>
                      <p className="text-sm text-light-muted dark:text-dark-muted">{service.description}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {service.is_critical && (
                      <span className="px-2 py-1 bg-severity-critical/20 text-severity-critical text-xs rounded-full">
                        Critical
                      </span>
                    )}
                    <button className="p-2 text-light-muted dark:text-dark-muted hover:text-brand-primary transition">
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteService(service.name)}
                      className="p-2 text-light-muted dark:text-dark-muted hover:text-severity-critical transition"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Health Metrics */}
                <div className="grid grid-cols-4 gap-4 mb-4">
                  <div className="text-center p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-1">Status</p>
                    <p className={`text-sm font-semibold ${health.status === 'healthy' ? 'text-brand-success' : 'text-severity-critical'}`}>
                      {health.status === 'healthy' ? 'Healthy' : 'Degraded'}
                    </p>
                  </div>
                  <div className="text-center p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-1">Uptime</p>
                    <p className="text-sm font-semibold text-light-text dark:text-dark-text">{health.uptime.toFixed(1)}%</p>
                  </div>
                  <div className="text-center p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-1">Error Rate</p>
                    <p className="text-sm font-semibold text-light-text dark:text-dark-text">{health.errorRate}%</p>
                  </div>
                  <div className="text-center p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-1">Incidents</p>
                    <p className="text-sm font-semibold text-light-text dark:text-dark-text">{health.activeIncidents}/{health.totalIncidents}</p>
                  </div>
                </div>

                {/* Owner & Dependencies */}
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <User className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                    <span className="text-light-muted dark:text-dark-muted">On-Call:</span>
                    <span className="text-light-text dark:text-dark-text">
                      {service.on_call.length > 0 ? service.on_call.join(', ') : 'No one assigned'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-light-muted dark:text-dark-muted" />
                    <span className="text-light-muted dark:text-dark-muted">Dependencies:</span>
                    <span className="text-light-text dark:text-dark-text">
                      {service.dependencies.length > 0 ? service.dependencies.join(', ') : 'None'}
                    </span>
                  </div>
                </div>

                {/* Recent Incidents */}
                {health.totalIncidents > 0 && (
                  <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
                    <p className="text-xs text-light-muted dark:text-dark-muted mb-2">Recent Incidents</p>
                    <div className="space-y-2">
                      {incidents.filter(i => i.service_name === service.name).slice(0, 3).map((incident) => (
                        <div key={incident.incident_id} className="flex items-center gap-3 p-2 bg-light-surface dark:bg-dark-surface rounded-lg">
                          <AlertTriangle className={`w-4 h-4 ${
                            incident.severity === 'P0' ? 'text-severity-critical' :
                            incident.severity === 'P1' ? 'text-severity-high' :
                            'text-brand-warning'
                          }`} />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-light-text dark:text-dark-text truncate">{incident.title}</p>
                            <p className="text-xs text-light-muted dark:text-dark-muted">{new Date(incident.declared_at).toLocaleString()}</p>
                          </div>
                          <span className={`text-xs px-2 py-0.5 rounded-full ${
                            incident.status === 'active' ? 'bg-severity-critical/20 text-severity-critical' : 'bg-brand-success/20 text-brand-success'
                          }`}>
                            {incident.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Right Column - Health Overview */}
        <div className="space-y-6">
          <ServiceHealthRing services={services} incidents={incidents} />
          <div className="bg-gradient-to-br from-light-card to-light-surface dark:from-dark-card dark:to-dark-surface rounded-2xl border border-light-border dark:border-dark-border shadow-xl p-6 backdrop-blur-sm">
            <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">Service Health Overview</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-brand-success"></div>
                  <span className="text-sm text-light-text dark:text-dark-text">Healthy Services</span>
                </div>
                <span className="text-sm font-semibold text-brand-success">
                  {services.filter(s => getServiceHealth(s.name).status === 'healthy').length}
                </span>
              </div>
              <div className="flex items-center justify-between p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full bg-severity-critical"></div>
                  <span className="text-sm text-light-text dark:text-dark-text">Degraded Services</span>
                </div>
                <span className="text-sm font-semibold text-severity-critical">
                  {services.filter(s => getServiceHealth(s.name).status === 'degraded').length}
                </span>
              </div>
              <div className="flex items-center justify-between p-3 bg-light-surface dark:bg-dark-surface rounded-lg">
                <div className="flex items-center gap-2">
                  <Server className="w-3 h-3 text-light-muted dark:text-dark-muted" />
                  <span className="text-sm text-light-text dark:text-dark-text">Total Services</span>
                </div>
                <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                  {services.length}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}