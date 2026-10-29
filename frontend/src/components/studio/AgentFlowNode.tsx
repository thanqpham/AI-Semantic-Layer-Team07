'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { CheckCircle2, CircleAlert, Loader2 } from 'lucide-react';
import { memo } from 'react';

import { BotMessageSquareIcon } from '@/components/ui/BotMessageSquareIcon';
import { useLanguage } from '@/context/LanguageContext';
import type { AgentFlowNode as AgentFlowNodeType, AgentStatus } from '@/lib/agentFlowGraph';
import { cn } from '@/lib/utils';

function getStatusText(status: AgentStatus, t: (en: string, vi: string) => string): string {
  switch (status) {
    case 'running':
      return t('Running', 'Đang chạy');
    case 'completed':
      return t('Completed', 'Hoàn tất');
    case 'error':
      return t('Error', 'Có lỗi');
    case 'idle':
    default:
      return t('Idle', 'Chờ xử lý');
  }
}

function StatusIndicator({ status }: { status: AgentStatus }) {
  switch (status) {
    case 'running':
      return (
        <Loader2
          aria-hidden
          className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500 motion-reduce:animate-none"
        />
      );
    case 'completed':
      return <CheckCircle2 aria-hidden className="h-3.5 w-3.5 shrink-0 text-emerald-500" />;
    case 'error':
      return <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0 text-red-500" />;
    case 'idle':
    default:
      return <span aria-hidden className="h-2 w-2 rounded-full bg-muted-foreground/40" />;
  }
}

/**
 * Custom card node for Agent Flow in Thinking accordion.
 * Displays agent icon, localized name, status badge, selection state, and handles.
 */
function AgentFlowNodeComponent({ data, selected }: NodeProps<AgentFlowNodeType>) {
  const { language, t } = useLanguage();
  const status = data?.status ?? 'idle';
  const displayName = language === 'en'
    ? (data?.enName || data?.name || 'Agent')
    : (data?.name || data?.enName || 'Agent');
  const statusText = getStatusText(status, t);
  const isSelected = Boolean(data?.selected || selected);

  const handleClick = () => {
    data?.onSelect?.(data.id);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.currentTarget.click();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${displayName} · ${statusText}`}
      aria-pressed={isSelected}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        'relative flex h-[56px] w-[180px] items-center gap-2.5 rounded-lg border bg-card px-3 py-2 text-card-foreground shadow-xs transition-all outline-none',
        isSelected ? 'border-primary ring-2 ring-primary' : 'border-border hover:border-foreground/20',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-muted-foreground/50 !border-background"
        isConnectable={false}
      />
      <BotMessageSquareIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium leading-tight" title={displayName}>
          {displayName}
        </div>
        <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
          {statusText}
        </div>
      </div>
      <div className="flex h-4 w-4 shrink-0 items-center justify-center">
        <StatusIndicator status={status} />
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-muted-foreground/50 !border-background"
        isConnectable={false}
      />
    </div>
  );
}

export const AgentFlowNode = memo(AgentFlowNodeComponent);
export default AgentFlowNode;
