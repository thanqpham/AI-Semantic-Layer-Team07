import type { SVGProps } from 'react';

export function EditIcon({ size = 24, ...props }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg width={size} height={size} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2">
        <path className="edit-icon-pen" strokeDasharray="44" d="M7 17v-4l10 -10l4 4l-10 10h-4" />
        <path className="edit-icon-base" strokeDasharray="20" d="M3 21h18" />
        <path className="edit-icon-detail" strokeDasharray="8" d="M14 6l4 4" />
      </g>
    </svg>
  );
}
