'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import {
  createWorkspaceApi,
  listWorkspacesApi,
  WorkspaceRole,
  WorkspaceSummary,
} from '@/lib/api';

interface WorkspaceContextValue {
  workspaces: WorkspaceSummary[];
  currentWorkspace: WorkspaceSummary | null;
  role: WorkspaceRole | null;
  permissions: Record<string, boolean>;
  isLoading: boolean;
  switchWorkspace: (id: number) => void;
  reloadWorkspaces: () => Promise<void>;
  createWorkspace: (name: string) => Promise<WorkspaceSummary>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

const defaultWorkspaceContext: WorkspaceContextValue = {
  workspaces: [],
  currentWorkspace: null,
  role: null,
  permissions: {},
  isLoading: false,
  switchWorkspace: () => {},
  reloadWorkspaces: async () => {},
  createWorkspace: async () => {
    throw new Error('Authentication required');
  },
};

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const requestGeneration = useRef(0);

  const reloadWorkspaces = useCallback(async () => {
    const generation = ++requestGeneration.current;
    if (!token) {
      setWorkspaces([]);
      setCurrentId(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const items = await listWorkspacesApi();
      if (generation !== requestGeneration.current) return;
      setWorkspaces(items);
      if (!items.length) {
        setCurrentId(null);
        return;
      }
      const stored = Number(window.localStorage.getItem('current_organization_id'));
      const selected = items.some((item) => item.id === stored) ? stored : items[0]?.id;
      if (selected) {
        setCurrentId(selected);
        window.localStorage.setItem('current_organization_id', String(selected));
      }
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setWorkspaces([]);
      setCurrentId(null);
      throw error;
    } finally {
      if (generation === requestGeneration.current) setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void reloadWorkspaces().catch(() => {});
  }, [reloadWorkspaces]);

  const switchWorkspace = useCallback((id: number) => {
    setCurrentId(id);
    window.localStorage.setItem('current_organization_id', String(id));
  }, []);

  const createWorkspace = useCallback(async (name: string): Promise<WorkspaceSummary> => {
    if (!token) throw new Error('Authentication required');
    const created = await createWorkspaceApi(name);
    try {
      await reloadWorkspaces();
    } catch {
      // Keep the API response available when the follow-up list request is unavailable.
    }
    setWorkspaces((current) =>
      current.some((item) => item.id === created.id) ? current : [...current, created],
    );
    switchWorkspace(created.id);
    return created;
  }, [reloadWorkspaces, switchWorkspace, token]);

  const currentWorkspace = useMemo(
    () => workspaces.find((item) => item.id === currentId) || null,
    [currentId, workspaces],
  );

  return (
    <WorkspaceContext.Provider
      value={{
        workspaces,
        currentWorkspace,
        role: currentWorkspace?.role || null,
        permissions: currentWorkspace?.permissions || {},
        isLoading,
        switchWorkspace,
        reloadWorkspaces,
        createWorkspace,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  return context || defaultWorkspaceContext;
}
