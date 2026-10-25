import type { SVGProps } from 'react';

export function BuildingOffice2Icon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`building-office-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" {...props}>
      <path d="M2.25 21h19.5m-18-18v18m10.5-18v18m6-13.5V21M6.75 21v-3.375c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21M3 3h12m-.75 4.5H21" />
      <path className="building-office-window building-office-window-1" d="M6.75 12.75h.75" />
      <path className="building-office-window building-office-window-2" d="M6.75 9.75h.75" />
      <path className="building-office-window building-office-window-3" d="M6.75 6.75h.75" />
      <path className="building-office-window building-office-window-1" d="M10.5 12.75h.75" />
      <path className="building-office-window building-office-window-2" d="M10.5 9.75h.75" />
      <path className="building-office-window building-office-window-3" d="M10.5 6.75h.75" />
      <path className="building-office-window building-office-window-1" d="M17.25 17h.008v.008h-.008v-.008Z" />
      <path className="building-office-window building-office-window-2" d="M17.25 14h.008v.008h-.008v-.008Z" />
      <path className="building-office-window building-office-window-3" d="M17.25 11h.008v.008h-.008v-.008Z" />
    </svg>
  );
}
