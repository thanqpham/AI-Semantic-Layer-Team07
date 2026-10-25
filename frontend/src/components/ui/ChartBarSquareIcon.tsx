import type { SVGProps } from 'react';

export function ChartBarSquareIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`chart-bar-square-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" {...props}>
      <path d="M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" />
      <path className="chart-bar-square-bar chart-bar-square-bar-1" pathLength="1" d="M7.5 14.25v2.25" />
      <path className="chart-bar-square-bar chart-bar-square-bar-2" pathLength="1" d="M10.5 12v4.5" />
      <path className="chart-bar-square-bar chart-bar-square-bar-3" pathLength="1" d="M13.5 9.75v6.75" />
      <path className="chart-bar-square-bar chart-bar-square-bar-4" pathLength="1" d="M16.5 7.5v9" />
    </svg>
  );
}
