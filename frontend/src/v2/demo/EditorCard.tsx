import type { ReactNode } from 'react';

interface EditorCardProps {
  fileName: string;
  isVerified: boolean;
  children: ReactNode;
}

export function EditorCard({ fileName, isVerified, children }: EditorCardProps) {
  return (
    <div className="rounded-xl overflow-hidden border border-slate-700 bg-[#1e1e2e] flex flex-col shadow-2xl">
      {/* macOS-style title bar */}
      <div className="flex items-center gap-2 px-4 h-10 bg-[#2a2a3a] select-none flex-shrink-0 border-b border-slate-700">
        {/* Traffic-light dots — always colored like macOS */}
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-[#FF5F57] shadow-sm" title="Close" />
          <div className="w-3 h-3 rounded-full bg-[#FEBC2E] shadow-sm" title="Minimise" />
          <div className={`w-3 h-3 rounded-full shadow-sm ${isVerified ? 'bg-[#28C840]' : 'bg-[#28C840] opacity-40'}`} title="Maximise" />
        </div>

        {/* File name — centred in the bar */}
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs text-slate-400 font-mono tracking-tight">{fileName}</span>
        </div>

        {/* Verified badge — right side */}
        {isVerified ? (
          <span className="text-xs text-green-400 font-medium flex items-center gap-1">
            <span>✓</span>
            <span>Verified</span>
          </span>
        ) : (
          <div className="w-16" /> /* spacer to keep filename centred */
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
