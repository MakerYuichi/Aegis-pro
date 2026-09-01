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
      <div className="absolute inset-0 bg-black/50" onClick={onClose}></div>
      
      {/* Modal */}
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">Declare Incident</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 rounded-lg transition"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Service <span className="text-red-500">*</span>
            </label>
            <select
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
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
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Message <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What's happening?"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Stack Trace <span className="text-gray-400 text-xs">(optional)</span>
            </label>
            <textarea
              value={stackTrace}
              onChange={(e) => setStackTrace(e.target.value)}
              placeholder="Paste your stack trace here..."
              rows={4}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent font-mono text-sm"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition disabled:opacity-50 flex items-center justify-center gap-2"
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