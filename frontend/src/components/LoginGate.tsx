import { useAuth0 } from '@auth0/auth0-react';

interface LoginGateProps {
  error?: Error | null;
}

export function LoginGate({ error }: LoginGateProps) {
  const { loginWithRedirect } = useAuth0();

  const login = () =>
    loginWithRedirect({
      authorizationParams: {
        audience: import.meta.env.VITE_AUTH0_AUDIENCE,
      },
    });

  const signup = () =>
    loginWithRedirect({
      authorizationParams: {
        screen_hint: 'signup',
        audience: import.meta.env.VITE_AUTH0_AUDIENCE,
      },
    });

  return (
    <div className="min-h-screen flex items-center justify-center bg-light-bg dark:bg-dark-bg">
      <div className="max-w-md w-full mx-auto p-8 bg-white dark:bg-gray-800 rounded-lg shadow-lg">
        <h1 className="text-3xl font-bold text-center mb-2">🛡️ AEGIS PRO</h1>
        <p className="text-center text-gray-500 mb-8">
          Turns an alert into a reviewed fix PR. Sign in to continue.
        </p>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error.message}
          </div>
        )}

        <div className="space-y-3">
          <button
            onClick={login}
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
          >
            Log In
          </button>
          <button
            onClick={signup}
            className="w-full py-3 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg font-medium transition-colors"
          >
            Sign Up
          </button>
        </div>
      </div>
    </div>
  );
}