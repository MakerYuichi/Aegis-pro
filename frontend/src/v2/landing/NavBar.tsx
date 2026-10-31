export function NavBar() {
  return (
    <nav className="sticky top-0 z-10 bg-aegis-bg/90 backdrop-blur-sm border-b border-aegis-line">
      <div className="max-w-7xl mx-auto px-4 h-12 flex items-center justify-between">
        <span className="font-semibold text-slate-100">AEGIS PRO</span>
        <div className="flex items-center gap-6">
          <a
            href="/demo"
            className="text-sm text-slate-400 hover:text-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber rounded"
          >
            Try live demo
          </a>
          <a
            href="https://github.com/MakerYuichi/Aegis-pro"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-slate-400 hover:text-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber rounded"
          >
            GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}
