import { useEffect, useRef } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { useProtectedApi } from '../utils/api';

/**
 * On authentication, ask the backend to link the current demo
 * session (identified by the httpOnly demo_session_id cookie) to
 * the signed-in user's email.
 *
 * The cookie is httpOnly, so the frontend cannot read it directly.
 * The backend reads it from the request. All this hook does is
 * trigger the call once per authentication transition.
 *
 * Fails silently — the link is a side-channel. A failure must not
 * break the dashboard.
 */
export function useDemoSessionLink() {
  const { isAuthenticated } = useAuth0();
  const { linkDemoSession } = useProtectedApi();

  // Hold the latest function in a ref so dependency array churn
  // (useProtectedApi returns a new object per render) can't cause
  // looped firing.
  const linkRef = useRef(linkDemoSession);
  useEffect(() => {
    linkRef.current = linkDemoSession;
  }, [linkDemoSession]);

  useEffect(() => {
    if (!isAuthenticated) return;

    console.log('[useDemoSessionLink] calling /me/link-demo-session...');
    linkRef.current()
      .then((res) => {
        console.log('[useDemoSessionLink] response:', res);
      })
      .catch((err) => {
        console.warn('[useDemoSessionLink] failed:', err);
      });
  }, [isAuthenticated]);
}
