# AEGIS PRO frontend

React + TypeScript dashboard and the public `/demo` landing page.

```bash
cp .env.example .env
npm install
npm run dev
```

- Signed out `/` and `/demo` → `DemoPage` (paste a public GitHub URL).
- Signed in `/` → operator dashboard. `IncidentView` renders incidents for both.

Auth0 SPA settings: `VITE_AUTH0_DOMAIN`, `VITE_AUTH0_CLIENT_ID`, `VITE_AUTH0_AUDIENCE`. API base: `VITE_API_URL` (default `http://localhost:8000`).
