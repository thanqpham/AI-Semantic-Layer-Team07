import { semanticRequest } from './api';
export interface RelationshipEntity { id: number; schema?: string | null; name: string; columns: { id: number; name: string; type: string; is_primary_key?: boolean }[] }
export interface ColumnPair { from_column_id: number; to_column_id: number }
export type RelationshipType = 'many_to_one' | 'one_to_one' | 'one_to_many' | 'many_to_many';
export interface RelationshipDraft { from_entity_id: number; to_entity_id: number; column_pairs: ColumnPair[]; relationship_type: RelationshipType; cardinality_confirmation?: string | null; expected_revision?: number }
export interface RelationshipReference { kind: 'active' | 'candidate'; id: number }
export interface RelationshipDiagnostic { code?: string; message: string; pair_index?: number; field?: string }
export interface RelationshipItem extends RelationshipReference {
  active_relationship_id?: number | null; revision: number; from_entity: RelationshipEntity; to_entity: RelationshipEntity;
  column_pairs: unknown; relationship_type: RelationshipType; source: string; status: string;
  evidence: Record<string, unknown>; confidence?: number | null; unresolved_questions: string[];
  reviewed_by?: number | null; reviewer_name?: string | null; reviewed_at?: string | null;
  on_preview: string; errors: RelationshipDiagnostic[]; warnings: RelationshipDiagnostic[];
}
export interface RelationshipList { items: RelationshipItem[]; counts: { pending_relationships: number; [key: string]: number } }
export interface RelationshipWrite { item: RelationshipItem; counts: RelationshipList['counts'] }
export interface RelationshipPreview { on_preview: string; errors: RelationshipDiagnostic[]; warnings: RelationshipDiagnostic[] }
export interface RelationshipImpact { token: string; relationship_ids: number[]; metric_ids: number[]; join_paths: number[][]; published_metrics: { id?: number; metric_id?: number; name?: string }[]; warnings: RelationshipDiagnostic[]; before_on: string; after_on: string }
export interface RelationshipDecision { expected_revision: number; impact_token?: string; acknowledge_impact?: boolean }
const base = (dbId: string) => `/api/v1/semantic/${dbId}/relationships`;
export function listRelationships(dbId: string, status = '', search = ''): Promise<RelationshipList> {
  const query = new URLSearchParams(); if (status) query.set('status', status); if (search) query.set('search', search);
  return semanticRequest(base(dbId) + (query.size ? `?${query}` : ''));
}
export function suggestRelationships(dbId: string): Promise<RelationshipList> { return semanticRequest(base(dbId) + '/suggest', { method: 'POST' }); }
export function previewRelationship(dbId: string, draft: RelationshipDraft): Promise<RelationshipPreview> { return semanticRequest(base(dbId) + '/preview', {method:'POST',body:JSON.stringify(draft)}); }
export function saveRelationship(dbId: string, draft: RelationshipDraft, item?: RelationshipReference | null): Promise<RelationshipWrite> {
  const path = !item ? '/candidates' : item.kind === 'active' ? `/${item.id}/edit` : `/candidates/${item.id}`;
  return semanticRequest(base(dbId) + path, {method:item?.kind === 'candidate' ? 'PATCH' : 'POST',body:JSON.stringify(draft)});
}
export function getRelationshipImpact(dbId: string, item: RelationshipReference, action: 'approve' | 'disable'): Promise<RelationshipImpact> {
  return semanticRequest(`${base(dbId)}/${item.id}/impact?kind=${item.kind}&action=${action}`);
}
export function decideRelationship(dbId: string, item: RelationshipReference, action: 'approve' | 'reject' | 'disable', decision: RelationshipDecision): Promise<RelationshipWrite> {
  return semanticRequest(`${base(dbId)}/${item.kind === 'candidate' ? 'candidates/' : ''}${item.id}/${action}`, {method:'POST',body:JSON.stringify(decision)});
}
export const qualifiedEntity = (entity: RelationshipEntity) => [entity.schema, entity.name].filter(Boolean).join('.');
