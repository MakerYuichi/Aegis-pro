export function DemoBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-brand-warning/15 text-brand-warning border border-brand-warning/30 ${className}`}
      title="This is simulated demo data — not a real incident"
    >
      DEMO
    </span>
  );
}