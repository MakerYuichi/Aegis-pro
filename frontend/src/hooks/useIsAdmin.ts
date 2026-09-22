import { useEffect, useState } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { useAdminApi } from '../utils/api';

type State = {
  isAdmin: boolean;
  loading: boolean;
  email: string | null;
};

let cachedState: State | null = null;

export function useIsAdmin(): State {
  const { isAuthenticated } = useAuth0();

  const [state, setState] = useState<State>(
    cachedState ?? { isAdmin: false, loading: isAuthenticated, email: null }
  );

  const adminApi = useAdminApi();

  useEffect(() => {
    if (!isAuthenticated) {
      cachedState = null;
      setState({ isAdmin: false, loading: false, email: null });
      return;
    }
    if (cachedState) return;

    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));

    adminApi
      .fetchMe()
      .then((me) => {
        if (cancelled) return;
        const next: State = {
          isAdmin: me.is_admin,
          loading: false,
          email: me.email,
        };
        cachedState = next;
        setState(next);
      })
      .catch(() => {
        if (cancelled) return;
        // Fail closed: a broken /me means no admin link.
        const next: State = { isAdmin: false, loading: false, email: null };
        cachedState = next;
        setState(next);
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, adminApi]);

  return state;
}
