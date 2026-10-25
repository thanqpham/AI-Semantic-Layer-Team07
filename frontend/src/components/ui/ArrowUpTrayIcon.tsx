import type { SVGProps } from 'react';

export function ArrowUpTrayIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`arrow-up-tray-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" {...props}>
      <path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5" />
      <g className="arrow-up-tray-arrow">
        <path d="M7.5 7.5L12 3m0 0 4.5 4.5M12 3v13.5" />
      </g>
    </svg>
  );
}
