// [review:need-review] #302
// summary: the card every dashboard block sits in - a labelled section with a title row and an optional line on the right, so all seven blocks share one frame and one heading level

import { useId, type ReactNode } from 'react';

interface DashboardCardProps {
  title: ReactNode;
  /** A short line on the right of the title: a count, a range, a link. */
  aside?: ReactNode;
  /** Grey and dashed: the block is announced but has nothing to show yet. */
  muted?: boolean;
  mobile?: boolean;
  className?: string;
  children: ReactNode;
}

export function DashboardCard({
  title,
  aside,
  muted = false,
  mobile = false,
  className = '',
  children,
}: DashboardCardProps) {
  const headingId = useId();
  const frame = muted ? 'border-dashed border-white/10 bg-surface' : 'border-white/5 bg-card';
  return (
    <section
      aria-labelledby={headingId}
      className={`rounded-3xl border ${frame} ${mobile ? 'p-4' : 'p-6'} ${className}`}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2
          id={headingId}
          className={`font-semibold text-text-primary ${mobile ? 'text-lg' : 'text-[22px]'}`}
        >
          {title}
        </h2>
        {aside !== undefined && <div className="shrink-0 text-[13px] text-text-secondary">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

/** The line a block shows when the server sent nothing for it; never a zero in its place. */
export function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="py-4 text-sm text-text-secondary">{children}</p>;
}
