import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RelationshipsPanel } from './RelationshipsPanel';
import * as api from '@/lib/relationshipReviewApi';
import { SemanticApiError } from '@/lib/api';
vi.mock('@/lib/relationshipReviewApi', async original => ({...await original<typeof import('@/lib/relationshipReviewApi')>(), listRelationships:vi.fn(), previewRelationship:vi.fn(), getRelationshipImpact:vi.fn(), suggestRelationships:vi.fn(), decideRelationship:vi.fn(), saveRelationship:vi.fn()}));
vi.mock('@/lib/api', async (original) => ({ ...await original<typeof import('@/lib/api')>(), getSchemaReviewApi: vi.fn(async () => ({tables: [
  {table_id:1, table_name:'orders', physical_schema:'sales', columns:[{column_id:10,column_name:'customer_id',data_type:'int'}]},
  {table_id:2, table_name:'customers', physical_schema:'sales',columns:[{column_id:20,column_name:'id',data_type:'int'}]},
]})) }));
const item: api.RelationshipItem = {kind:'candidate',id:1,revision:2,from_entity:{id:1,schema:'sales',name:'orders',columns:[{id:10,name:'customer_id',type:'int'}]},to_entity:{id:2,schema:'sales',name:'customers',columns:[{id:20,name:'id',type:'int'}]}, column_pairs:[{from_column_id:10,to_column_id:20}],relationship_type:'many_to_one',source:'ai',status:'pending_review', evidence:{reason:'matching metadata'},reviewer_name:'Lan',reviewed_at:'2026-10-27',on_preview:'orders.customer_id = customers.id',errors:[],warnings:[],unresolved_questions:[]};
const result = {items:[item],counts:{pending_relationships:1}};
const changed=vi.fn();
beforeEach(() => {vi.clearAllMocks();vi.mocked(api.listRelationships).mockResolvedValue(result);vi.mocked(api.previewRelationship).mockResolvedValue({on_preview:item.on_preview,errors:[],warnings:[]});vi.mocked(api.getRelationshipImpact).mockResolvedValue({token:'t',metric_ids:[9],relationship_ids:[1],join_paths:[[1,2]],published_metrics:[{id:9,name:'Revenue'}],warnings:[],before_on:'old',after_on:'new'});});
afterEach(cleanup);
const setup=(manage=true, approve=true) => render(<RelationshipsPanel dbId="7" canManageSchema={manage} canApproveSchema={approve} onReviewChanged={changed} initialView="list"/>);
it('restores the selected preview after an invalid draft returns to baseline', async () => {
 vi.mocked(api.previewRelationship).mockResolvedValue({on_preview:'invalid',errors:[{message:'Invalid draft'}],warnings:[]});
 setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
 const input=screen.getByLabelText('Xác nhận cardinality khi thiếu bằng chứng khóa');
 fireEvent.change(input,{target:{value:'changed'}});
 expect(await screen.findByRole('alert')).toHaveTextContent('Invalid draft');
 fireEvent.change(input,{target:{value:''}});
 await waitFor(()=>expect(screen.queryByRole('alert')).not.toBeInTheDocument());
 expect(screen.getByRole('button',{name:'Xác nhận'})).toBeEnabled();
 expect(screen.getByText(item.on_preview)).toBeInTheDocument();
});
it('returns focus to the dirty-dialog invoker after Continue and Escape', async () => {
 setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
 fireEvent.click(screen.getByRole('button',{name:'Thêm cặp cột'}));
 const back=screen.getByRole('button',{name:'Quay lại danh sách'});
 back.focus();fireEvent.click(back);
 fireEvent.click(screen.getByRole('button',{name:'Tiếp tục chỉnh sửa'}));
 await waitFor(()=>expect(back).toHaveFocus());
 fireEvent.click(back);fireEvent.keyDown(screen.getByRole('dialog'),{key:'Escape'});
 await waitFor(()=>expect(back).toHaveFocus());
});
it('selects detail, preserves selection after suggestions and requires impact acknowledgment', async () => {
  vi.mocked(api.suggestRelationships).mockResolvedValue({items:[{...item,id:2}],counts:{pending_relationships:2}});
  vi.mocked(api.decideRelationship).mockResolvedValue({item:{...item,status:'approved'},counts:{pending_relationships:0}});
  setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
  expect(screen.getByText('N → 1')).toBeInTheDocument();expect(screen.getByText('Lan')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'AI đề xuất'}));
  await waitFor(()=>expect(api.suggestRelationships).toHaveBeenCalled());
  expect(screen.getByRole('heading',{name:/sales.orders/})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Xác nhận'}));
  expect(await screen.findByText(/Revenue/)).toBeInTheDocument();
  const confirm=screen.getByRole('button',{name:'Xác nhận tác động'});expect(confirm).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(confirm);
  await waitFor(()=>expect(changed).toHaveBeenCalled());
  expect(api.decideRelationship).toHaveBeenCalledWith('7',expect.objectContaining({id:1}), 'approve',expect.objectContaining({impact_token:'t',acknowledge_impact:true}));
});
it('limits mutation by role and offers back focus with dirty cancellation', async () => {
 setup(false,false);const row=await screen.findByRole('button',{name:/sales.orders.*sales.customers/});fireEvent.click(row);
 expect(screen.queryByRole('button',{name:'Lưu đề xuất'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Quay lại danh sách'}));await waitFor(()=>expect(row).toHaveFocus());
});
it('does not apply an old database response', async () => {
 let resolve!: (value:api.RelationshipList)=>void;
 vi.mocked(api.listRelationships).mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockResolvedValue({items:[],counts:{pending_relationships:0}});
 const {rerender}=setup();rerender(<RelationshipsPanel dbId="8" canManageSchema canApproveSchema onReviewChanged={changed}/>);
 await screen.findByText('Chưa có liên kết.');resolve(result);
 await waitFor(()=>expect(screen.queryByRole('button',{name:/sales.orders.*sales.customers/})).not.toBeInTheDocument());
});

it('filters qualified columns and retries a failed list', async () => {
 vi.mocked(api.listRelationships).mockRejectedValueOnce(new Error('Offline'));
 setup();expect(await screen.findByRole('alert')).toHaveTextContent('Offline');fireEvent.click(screen.getByRole('button',{name:'Thử lại'}));
 await screen.findByRole('button',{name:/sales.orders.*sales.customers/});
 fireEvent.change(screen.getByRole('textbox',{name:'Tìm liên kết'}),{target:{value:'sales.orders.customer_id'}});
 fireEvent.change(screen.getByRole('combobox',{name:'Trạng thái liên kết'}),{target:{value:'pending_review'}});
 await waitFor(()=>expect(api.listRelationships).toHaveBeenLastCalledWith('7','pending_review','sales.orders.customer_id'));
});
it('clears columns when tables change, supports composite rows, and guards dirty back', async () => {
 setup(true,false);fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
 expect(screen.queryByRole('button',{name:'Xác nhận'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Thêm cặp cột'}));expect(screen.getByRole('combobox',{name:'Cột nguồn 2'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Xóa cặp 2'}));
 fireEvent.change(screen.getByRole('combobox',{name:'Bảng nguồn'}),{target:{value:'2'}});
 const source=screen.getByRole('combobox',{name:'Cột nguồn 1'});expect(source).toHaveValue('0');
 expect(within(source).queryByRole('option',{name:'customer_id (int)'})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Lưu đề xuất'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Quay lại danh sách'}));expect(screen.getByRole('dialog')).toHaveTextContent('Bỏ chỉnh sửa chưa lưu?');
 fireEvent.click(screen.getByRole('button',{name:'Tiếp tục chỉnh sửa'}));expect(screen.getByRole('heading',{name:/sales.customers/})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Quay lại danh sách'}));fireEvent.click(screen.getByRole('button',{name:'Bỏ chỉnh sửa'}));expect(screen.queryByRole('heading')).not.toBeInTheDocument();
});
it('shows indexed validation errors and blocks save/approve', async () => {
 vi.mocked(api.previewRelationship).mockRejectedValue(new SemanticApiError(422,'Invalid',{errors:[{pair_index:0,field:'to_column_id',message:'Wrong column'}]}));
 setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
 fireEvent.change(screen.getByLabelText('Xác nhận cardinality khi thiếu bằng chứng khóa'),{target:{value:'confirmed'}});
 expect(await screen.findByRole('alert')).toHaveTextContent('Cặp 1: to_column_id: Wrong column');
 expect(screen.getByRole('button',{name:'Lưu đề xuất'})).toBeDisabled();expect(screen.getByRole('button',{name:'Xác nhận'})).toBeDisabled();
});
it('saves active edits as candidates while retaining the original active row', async () => {
 const active={...item,kind:'active' as const,status:'approved'};vi.mocked(api.listRelationships).mockResolvedValue({items:[active],counts:{pending_relationships:0}});
 vi.mocked(api.saveRelationship).mockResolvedValue({item:{...item,id:2,active_relationship_id:1},counts:{pending_relationships:1}});
 setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
 fireEvent.change(screen.getByLabelText('Xác nhận cardinality khi thiếu bằng chứng khóa'),{target:{value:'confirmed'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'Lưu đề xuất'})).toBeEnabled());fireEvent.click(screen.getByRole('button',{name:'Lưu đề xuất'}));
 expect(await screen.findByText(/liên kết gốc vẫn hoạt động/)).toBeInTheDocument();
 expect(api.saveRelationship).toHaveBeenCalledWith('7',expect.objectContaining({expected_revision:2}),expect.objectContaining({kind:'active',id:1}));
 expect(screen.getByRole('button',{name:/sales.orders.*sales.customers/})).toHaveTextContent('approved');
});
it('reloads a stale impact and requires a fresh acknowledgment', async () => {
 vi.mocked(api.decideRelationship).mockRejectedValueOnce(new SemanticApiError(409,'Stale revision'));
 setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));fireEvent.click(screen.getByRole('button',{name:'Xác nhận'}));
 fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Xác nhận tác động'}));
 await waitFor(()=>expect(api.getRelationshipImpact).toHaveBeenCalledTimes(2));
 expect(screen.getByRole('checkbox')).not.toBeChecked();expect(screen.getByRole('button',{name:'Xác nhận tác động'})).toBeDisabled();
});

 it('keeps malformed legacy pairs visible and allows a safe repair draft', async () => {
  const broken={...item,kind:'active' as const,status:'needs_review',column_pairs:['malformed'],errors:[{code:'INVALID_PAIR',message:'Invalid pair'}]};
  vi.mocked(api.listRelationships).mockResolvedValue({items:[broken],counts:{pending_relationships:0}});
  setup();fireEvent.click(await screen.findByRole('button',{name:/sales.orders.*sales.customers/}));
  expect(screen.getByText('["malformed"]')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox',{name:'Cột nguồn 1'}),{target:{value:'10'}});
  fireEvent.change(screen.getByRole('combobox',{name:'Cột đích 1'}),{target:{value:'20'}});
  await waitFor(()=>expect(api.previewRelationship).toHaveBeenCalledWith('7',expect.objectContaining({column_pairs:[{from_column_id:10,to_column_id:20}]})));
  expect(screen.getByText('["malformed"]')).toBeInTheDocument();
 });

 it('toggles between diagram and card list views', async () => {
   render(<RelationshipsPanel dbId="7" canManageSchema canApproveSchema onReviewChanged={changed} initialView="diagram" />);
   expect(screen.getByRole('button', { name: 'Sơ đồ' })).toHaveAttribute('aria-pressed', 'true');
   expect(screen.getByRole('button', { name: 'Danh sách' })).toHaveAttribute('aria-pressed', 'false');
   fireEvent.click(screen.getByRole('button', { name: 'Danh sách' }));
   expect(screen.getByRole('button', { name: 'Danh sách' })).toHaveAttribute('aria-pressed', 'true');
   expect(await screen.findByRole('button', { name: /sales.orders.*sales.customers/ })).toBeInTheDocument();
 });

 it('displays friendly message when account AI is not configured', async () => {
   vi.mocked(api.suggestRelationships).mockRejectedValueOnce(
     new SemanticApiError(503, 'Account AI settings are required', {
       errors: [{ code: 'ACCOUNT_LLM_NOT_CONFIGURED', message: 'Configure account AI settings' }],
     }),
   );
   setup();
   fireEvent.click(screen.getByRole('button', { name: 'AI đề xuất' }));
   expect(
     await screen.findByText('Hệ thống hoặc tài khoản chưa cấu hình API Key AI. Vui lòng cấu hình trong Cài đặt AI để tiếp tục.'),
   ).toBeInTheDocument();
 });

 it('displays friendly timeout message and retries suggestion when clicking Thử lại đề xuất', async () => {
   vi.mocked(api.suggestRelationships)
     .mockRejectedValueOnce(
       new SemanticApiError(422, 'Suggestion failed', {
         errors: [{ code: 'SUGGESTION_FAILED', message: 'Timeout' }],
       }),
     )
     .mockResolvedValueOnce({ items: [], counts: { pending_relationships: 0 } });
   setup();
   fireEvent.click(screen.getByRole('button', { name: 'AI đề xuất' }));
   expect(
     await screen.findByText('Quá trình AI đề xuất liên kết bị quá thời gian hoặc không thể phân tích schema. Vui lòng thử lại.'),
   ).toBeInTheDocument();
   const retryBtn = screen.getByRole('button', { name: 'Thử lại đề xuất' });
   fireEvent.click(retryBtn);
   await waitFor(() => expect(api.suggestRelationships).toHaveBeenCalledTimes(2));
 });

 it('notifies when no new relationships were found', async () => {
   const notify = vi.fn();
   vi.mocked(api.suggestRelationships).mockResolvedValueOnce({ items: [], counts: { pending_relationships: 0 } });
   render(<RelationshipsPanel dbId="7" canManageSchema canApproveSchema onReviewChanged={changed} onNotify={notify} initialView="list" />);
   fireEvent.click(screen.getByRole('button', { name: 'AI đề xuất' }));
   await waitFor(() => expect(notify).toHaveBeenCalledWith('Không tìm thấy liên kết mới nào từ schema'));
 });

