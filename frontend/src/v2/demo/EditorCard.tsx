import type { ReactNode } from 'react';

interface EditorCardProps {
  fileName: string;
  isVerified: boolean;
  children: ReactNode;
}

export function EditorCard({ fileName, isVerified, children }: EditorCardProps) {
  return (
    <div className="rounded-lg overflow-hidden border border-aegis-line bg-aegis-surface flex flex-col">
      {/* Title bar */}
      <div className="flex items-center gap-2 px-3 h-9 bg-aegis-line select-none flex-shrink-0">
        {/* Traffic-light dots */}
        <div className="w-3 h-3 rounded-full bg-slate-600" />
        <div className="w-3 h-3 rounded-full bg-slate-600" />
        <div className={`w-3 h-3 rounded-full ${isVerified ? 'bg-aegis-green' : 'bg-slate-600'}`} />

        {/* File name */}
        <span className="ml-2 text-sm text-slate-400 font-mono">{fileName}</span>

        {/* Verified badge */}
        {isVerified && (
          <span className="ml-auto text-xs text-aegis-green font-medium">✓ Verified</span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
