import { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import { declareIncident, type Service } from '../utils/api';

interface DeclareIncidentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  services: Service[];
}

export function DeclareIncidentModal({ isOpen, onClose, onSuccess, services }: DeclareIncidentModalProps) {
  const [serviceName, setServiceName] = useState('');
  const [message, setMessage] = useState('');
  const [stackTrace, setStackTrace] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!serviceName || !message) {
      setError('Please fill in all required fields');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      await declareIncident({
        service_name: serviceName,
        message: message,
        stack_trace: stackTrace || undefined,
      });
      onSuccess();
      onClose();
      // Reset form
      setServiceName('');
      setMessage('');
      setStackTrace('');
    } catch (err) {
      setError('Failed to declare incident. Please try again.');
      console.error('Error declaring incident:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose}></div>
      
      {/* Modal */}
      <div className="relative bg-light-card dark:bg-dark-card rounded-2xl shadow-2xl w-full max-w-lg mx-4 p-6 border border-light-border dark:border-dark-border">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-light-text dark:text-dark-text">Declare Incident</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-light-surface dark:hover:bg-dark-surface rounded-lg transition"
          >
            <X className="w-5 h-5 text-light-muted dark:text-dark-muted" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-1">
              Service <span className="text-severity-critical">*</span>
            </label>
            <select
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:ring-2 focus:ring-brand-primary focus:border-transparent"
              required
            >
              <option value="">Select a service...</option>
              {services.map((service) => (
                <option key={service.name} value={service.name}>
                  {service.name} {service.is_critical ? '⭐' : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-1">
              Message <span className="text-severity-critical">*</span>
            </label>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What's happening?"
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:ring-2 focus:ring-brand-primary focus:border-transparent"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-1">
              Stack Trace <span className="text-light-muted dark:text-dark-muted text-xs">(optional)</span>
            </label>
            <textarea
              value={stackTrace}
              onChange={(e) => setStackTrace(e.target.value)}
              placeholder="Paste your stack trace here..."
              rows={4}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:ring-2 focus:ring-brand-primary focus:border-transparent font-mono text-sm"
            />
          </div>

          {error && (
            <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-lg p-3 text-sm text-severity-critical">
              {error}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-light-border dark:border-dark-border rounded-lg hover:bg-light-surface dark:hover:bg-dark-surface transition text-light-text dark:text-dark-text"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-brand-primary hover:bg-brand-primary/90 text-white rounded-lg transition disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Declaring...
                </>
              ) : (
                'Declare Incident'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}