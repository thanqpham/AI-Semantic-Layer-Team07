'use client';

import { type FormEvent, useState } from 'react';

import { useWorkspace } from '@/context/WorkspaceContext';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

export interface CreateWorkspaceModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateWorkspaceModal({ isOpen, onClose }: CreateWorkspaceModalProps) {
  const { translate } = useLanguage();
  const { createWorkspace } = useWorkspace();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Tên Workspace không được để trống');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await createWorkspace(trimmed);
      setName('');
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể tạo Workspace');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !loading && onClose()}>
      <DialogContent className="bg-background sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl"><Translated text={"Tạo Workspace mới"} /></DialogTitle>
          <DialogDescription><Translated text={"Tạo một Workspace để quản lý dữ liệu và thành viên."} /></DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium"><Translated text={"Tên Workspace"} /></span>
            <input
              aria-label={translate("Tên Workspace")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={loading}
              autoFocus
              className="border-input bg-background text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-3 text-sm outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
            />
          </label>
          {error && (
            <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
              {error}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
              <Translated text={"Hủy"} />
            </Button>
            <Button type="submit" disabled={loading}>
              <Translated text={loading ? 'Đang tạo...' : 'Tạo Workspace'} />
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
