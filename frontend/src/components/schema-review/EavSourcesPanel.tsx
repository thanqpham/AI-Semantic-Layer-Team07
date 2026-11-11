'use client';

import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Translated } from '@/components/ui/translated';
import {
  createEavConfigApi,
  createEavMetricApi,
  listEavConfigsApi,
  reviewEavConfigApi,
  SemanticApiError,
  updateEavConfigApi,
  type EavAttribute,
  type EavConfig,
  type EavDataType,
  type EavMultiValueRule,
} from '@/lib/api';

interface Props {
  dbId: number | string;
  canManageSchema: boolean;
  canApproveMetrics: boolean;
  onNotify?: (message: string) => void;
  onMetricsChanged?: () => void;
}

interface AttributeDraft {
  key: string;
  label: string;
  data_type: EavDataType;
  rule: EavMultiValueRule;
  history: boolean;
}

interface FormState {
  name: string;
  entity_table: string;
  entity_id_column: string;
  attribute_mode: 'direct' | 'dictionary';
  attribute_column: string;
  attribute_fk_column: string;
  dict_table: string;
  dict_key_column: string;
  dict_label_column: string;
  value_number: string;
  value_string: string;
  history_effective: string;
  history_end: string;
  attributes: AttributeDraft[];
}

const emptyForm: FormState = {
  name: '',
  entity_table: '',
  entity_id_column: '',
  attribute_mode: 'direct',
  attribute_column: '',
  attribute_fk_column: '',
  dict_table: '',
  dict_key_column: '',
  dict_label_column: '',
  value_number: '',
  value_string: '',
  history_effective: '',
  history_end: '',
  attributes: [{ key: '', label: '', data_type: 'number', rule: 'reject', history: false }],
};

const DATA_TYPES: EavDataType[] = ['number', 'string', 'boolean', 'date', 'datetime'];
const RULES: EavMultiValueRule[] = ['reject', 'sum', 'avg', 'min', 'max'];

function payloadFromForm(form: FormState) {
  const value_columns: Record<string, string> = {};
  if (form.value_number.trim()) value_columns.number = form.value_number.trim();
  if (form.value_string.trim()) value_columns.string = form.value_string.trim();
  const dictionary = form.attribute_mode === 'dictionary';
  return {
    name: form.name.trim(),
    entity_table: form.entity_table.trim(),
    entity_id_column: form.entity_id_column.trim(),
    attribute_mode: form.attribute_mode,
    attribute_column: dictionary ? null : form.attribute_column.trim(),
    attribute_fk_column: dictionary ? form.attribute_fk_column.trim() : null,
    dict_table: dictionary ? form.dict_table.trim() || null : null,
    dict_key_column: dictionary ? form.dict_key_column.trim() || null : null,
    dict_label_column: dictionary ? form.dict_label_column.trim() || null : null,
    value_columns,
    history: form.history_effective.trim()
      ? { effective_column: form.history_effective.trim(), end_column: form.history_end.trim() || null }
      : null,
    attributes: form.attributes
      .filter((item) => item.key.trim())
      .map((item) => ({
        attribute_key: item.key.trim(),
        label: item.label.trim() || item.key.trim(),
        data_type: item.data_type,
        multi_value_rule: item.rule,
        history_enabled: item.history,
      })),
  };
}

function validationDetail(error: unknown): string {
  if (error instanceof SemanticApiError && Array.isArray(error.detail)) {
    return error.detail.filter((item): item is string => typeof item === 'string').join('; ');
  }
  return error instanceof Error ? error.message : 'Không thể lưu cấu hình EAV.';
}

function formFromConfig(config: EavConfig): FormState {
  return {
    name: config.name,
    entity_table: config.entity_table,
    entity_id_column: config.entity_id_column,
    attribute_mode: config.attribute_mode,
    attribute_column: config.attribute_column ?? '',
    attribute_fk_column: config.attribute_fk_column ?? '',
    dict_table: config.dict_table ?? '',
    dict_key_column: config.dict_key_column ?? '',
    dict_label_column: config.dict_label_column ?? '',
    value_number: config.value_columns.number ?? '',
    value_string: config.value_columns.string ?? '',
    history_effective: config.history?.effective_column ?? '',
    history_end: config.history?.end_column ?? '',
    attributes: config.attributes.map((item) => ({
      key: item.attribute_key,
      label: item.label,
      data_type: item.data_type,
      rule: item.multi_value_rule ?? 'reject',
      history: item.history_enabled ?? false,
    })),
  };
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      <Translated text={label} />
      {children}
    </label>
  );
}

function ConfigDetails({ config }: { config: EavConfig }) {
  const rows: Array<[string, string]> = [
    ['Bảng entity', config.entity_table],
    ['Cột định danh', config.entity_id_column],
    ['Kiểu nhận diện', config.attribute_mode],
    ['Cột mã thuộc tính', config.attribute_column ?? '—'],
    ['Cột liên kết từ điển', config.attribute_fk_column ?? '—'],
    ['Bảng từ điển', config.dict_table ?? '—'],
    ['Cột mã từ điển', config.dict_key_column ?? '—'],
    ['Cột nhãn từ điển', config.dict_label_column ?? '—'],
    ...Object.entries(config.value_columns).map(([type, column]): [string, string] => [`Cột giá trị ${type}`, column]),
    ['Cột hiệu lực (history)', config.history?.effective_column ?? '—'],
    ['Cột kết thúc (history)', config.history?.end_column ?? '—'],
  ];
  return (
    <div aria-label="Chi tiết cấu hình EAV" className="mt-2 flex flex-col gap-2 rounded-md border border-border bg-secondary/30 p-3 text-xs">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-col">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-2 font-medium">Khóa</th>
            <th className="py-1 pr-2 font-medium">Tên hiển thị</th>
            <th className="py-1 pr-2 font-medium">Kiểu</th>
            <th className="py-1 pr-2 font-medium">Quy tắc đa giá trị</th>
            <th className="py-1 font-medium">History</th>
          </tr>
        </thead>
        <tbody>
          {config.attributes.map((attribute) => (
            <tr key={attribute.id} className="border-t border-border">
              <td className="py-1 pr-2">{attribute.attribute_key}</td>
              <td className="py-1 pr-2">{attribute.label}</td>
              <td className="py-1 pr-2">{attribute.data_type}</td>
              <td className="py-1 pr-2">{attribute.multi_value_rule}</td>
              <td className="py-1">{attribute.history_enabled ? 'Bật' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EavSourcesPanel({ dbId, canManageSchema, canApproveMetrics, onNotify, onMetricsChanged }: Props) {
  const [configs, setConfigs] = useState<EavConfig[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    try {
      setConfigs(await listEavConfigsApi(dbId));
    } catch {
      setConfigs([]);
    }
  }, [dbId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setField = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));

  const submit = async () => {
    setBusy(true);
    setErrors([]);
    try {
      const payload = payloadFromForm(form);
      if (editingId !== null) {
        await updateEavConfigApi(dbId, editingId, payload);
        onNotify?.('Đã cập nhật cấu hình EAV. Trạng thái: chờ phê duyệt.');
      } else {
        await createEavConfigApi(dbId, payload);
        onNotify?.('Đã lưu cấu hình EAV. Trạng thái: chờ phê duyệt.');
      }
      setForm(emptyForm);
      setEditingId(null);
      setFormOpen(false);
      await reload();
    } catch (error) {
      setErrors([validationDetail(error)]);
    } finally {
      setBusy(false);
    }
  };

  const review = async (configId: number, action: 'approve' | 'reject') => {
    try {
      await reviewEavConfigApi(dbId, configId, action);
      onNotify?.(action === 'approve' ? 'Đã phê duyệt cấu hình EAV.' : 'Đã từ chối cấu hình EAV.');
      await reload();
    } catch (error) {
      onNotify?.(error instanceof Error ? error.message : 'Không thể xử lý cấu hình EAV.');
    }
  };

  const createMetric = async (configId: number, attribute: EavAttribute) => {
    try {
      await createEavMetricApi(dbId, configId, attribute.id, { aggregation: 'SUM' });
      onNotify?.(`Đã tạo metric từ thuộc tính "${attribute.label}".`);
      onMetricsChanged?.();
    } catch (error) {
      onNotify?.(error instanceof Error ? error.message : 'Không thể tạo metric từ thuộc tính EAV.');
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          <Translated text="Nguồn dữ liệu EAV" />
        </h3>
        {canManageSchema && (
          <Button
            variant="outline"
            className="h-7 text-xs"
            onClick={() => {
              setForm(emptyForm);
              setEditingId(null);
              setFormOpen((open) => !open);
            }}
            aria-label="Khai báo nguồn EAV"
          >
            <Translated text="Khai báo nguồn EAV" />
          </Button>
        )}
      </div>

      {formOpen && (
        <div className="flex flex-col gap-3 rounded-lg border border-border bg-secondary/40 p-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Tên cấu hình">
              <Input aria-label="Tên cấu hình" value={form.name} onChange={(e) => setField({ name: e.target.value })} />
            </Field>
            <Field label="Bảng entity">
              <Input
                aria-label="Bảng entity"
                value={form.entity_table}
                onChange={(e) => setField({ entity_table: e.target.value })}
              />
            </Field>
            <Field label="Cột định danh thực thể">
              <Input
                aria-label="Cột định danh thực thể"
                value={form.entity_id_column}
                onChange={(e) => setField({ entity_id_column: e.target.value })}
              />
            </Field>
            <Field label="Kiểu nhận diện thuộc tính">
              <select
                aria-label="Kiểu nhận diện thuộc tính"
                className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                value={form.attribute_mode}
                onChange={(e) => setField({ attribute_mode: e.target.value as FormState['attribute_mode'] })}
              >
                <option value="direct">Mã trực tiếp (direct)</option>
                <option value="dictionary">Bảng từ điển (dictionary)</option>
              </select>
            </Field>
            {form.attribute_mode === 'direct' ? (
              <Field label="Cột mã thuộc tính">
                <Input
                  aria-label="Cột mã thuộc tính"
                  value={form.attribute_column}
                  onChange={(e) => setField({ attribute_column: e.target.value })}
                />
              </Field>
            ) : (
              <>
                <Field label="Cột liên kết bảng từ điển">
                  <Input
                    aria-label="Cột liên kết bảng từ điển"
                    value={form.attribute_fk_column}
                    onChange={(e) => setField({ attribute_fk_column: e.target.value })}
                  />
                </Field>
                <Field label="Bảng từ điển">
                  <Input
                    aria-label="Bảng từ điển"
                    value={form.dict_table}
                    onChange={(e) => setField({ dict_table: e.target.value })}
                  />
                </Field>
                <Field label="Cột mã từ điển">
                  <Input
                    aria-label="Cột mã từ điển"
                    value={form.dict_key_column}
                    onChange={(e) => setField({ dict_key_column: e.target.value })}
                  />
                </Field>
                <Field label="Cột nhãn từ điển">
                  <Input
                    aria-label="Cột nhãn từ điển"
                    value={form.dict_label_column}
                    onChange={(e) => setField({ dict_label_column: e.target.value })}
                  />
                </Field>
              </>
            )}
            <Field label="Cột giá trị number">
              <Input
                aria-label="Cột giá trị number"
                value={form.value_number}
                onChange={(e) => setField({ value_number: e.target.value })}
              />
            </Field>
            <Field label="Cột giá trị string">
              <Input
                aria-label="Cột giá trị string"
                value={form.value_string}
                onChange={(e) => setField({ value_string: e.target.value })}
              />
            </Field>
            <Field label="Cột hiệu lực (history, tùy chọn)">
              <Input
                aria-label="Cột hiệu lực history tùy chọn"
                value={form.history_effective}
                onChange={(e) => setField({ history_effective: e.target.value })}
              />
            </Field>
            <Field label="Cột kết thúc (history, tùy chọn)">
              <Input
                aria-label="Cột kết thúc history tùy chọn"
                value={form.history_end}
                onChange={(e) => setField({ history_end: e.target.value })}
              />
            </Field>
          </div>

          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5" aria-label="Tiêu đề cột thuộc tính">
              <span className="text-xs font-medium text-muted-foreground">Khóa thuộc tính</span>
              <span className="text-xs font-medium text-muted-foreground">Tên hiển thị</span>
              <span className="text-xs font-medium text-muted-foreground">Kiểu dữ liệu</span>
              <span className="text-xs font-medium text-muted-foreground">Quy tắc đa giá trị</span>
              <span className="text-xs font-medium text-muted-foreground">History</span>
            </div>
            {form.attributes.map((attribute, index) => (
              <div key={index} className="grid grid-cols-2 gap-2 md:grid-cols-5">
                <Input
                  aria-label="Khóa thuộc tính"
                  placeholder="attribute_key"
                  value={attribute.key}
                  onChange={(e) =>
                    setField({
                      attributes: form.attributes.map((item, i) => (i === index ? { ...item, key: e.target.value } : item)),
                    })
                  }
                />
                <Input
                  aria-label="Tên hiển thị"
                  placeholder="Tên hiển thị"
                  value={attribute.label}
                  onChange={(e) =>
                    setField({
                      attributes: form.attributes.map((item, i) => (i === index ? { ...item, label: e.target.value } : item)),
                    })
                  }
                />
                <select
                  aria-label="Kiểu dữ liệu"
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                  value={attribute.data_type}
                  onChange={(e) =>
                    setField({
                      attributes: form.attributes.map((item, i) =>
                        i === index ? { ...item, data_type: e.target.value as EavDataType } : item,
                      ),
                    })
                  }
                >
                  {DATA_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Quy tắc đa giá trị"
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                  value={attribute.rule}
                  onChange={(e) =>
                    setField({
                      attributes: form.attributes.map((item, i) =>
                        i === index ? { ...item, rule: e.target.value as EavMultiValueRule } : item,
                      ),
                    })
                  }
                >
                  {RULES.map((rule) => (
                    <option key={rule} value={rule}>
                      {rule}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    aria-label="Bật history"
                    checked={attribute.history}
                    onChange={(e) =>
                      setField({
                        attributes: form.attributes.map((item, i) =>
                          i === index ? { ...item, history: e.target.checked } : item,
                        ),
                      })
                    }
                    className="h-3 w-3 accent-primary"
                  />
                  History
                </label>
              </div>
            ))}
            <Button
              variant="ghost"
              className="h-7 w-fit text-xs"
              onClick={() =>
                setField({
                  attributes: [...form.attributes, { key: '', label: '', data_type: 'string', rule: 'reject', history: false }],
                })
              }
            >
              + <Translated text="Thêm thuộc tính" />
            </Button>
          </div>

          {errors.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-md bg-destructive/10 p-2 text-xs text-destructive">
              {errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          )}

          <Button className="h-8 w-fit text-xs" disabled={busy} onClick={() => void submit()}>
            <Translated text="Lưu cấu hình" />
          </Button>
        </div>
      )}

      {configs.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          <Translated text="Chưa có nguồn EAV nào được khai báo cho database này." />
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {configs.map((config) => (
            <li key={config.id} className="rounded-lg border border-border bg-background p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs">
                  <span className="font-semibold text-foreground">{config.name}</span>
                  <span className="text-muted-foreground">
                    {' · '}
                    {config.entity_table} ({config.attribute_mode}) · <Translated text="trạng thái" />:{' '}
                    {config.review_status}
                  </span>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    className="h-7 text-xs"
                    aria-label={expandedId === config.id ? 'Ẩn cấu hình' : 'Xem cấu hình'}
                    onClick={() => setExpandedId(expandedId === config.id ? null : config.id)}
                  >
                    {expandedId === config.id ? <Translated text="Ẩn cấu hình" /> : <Translated text="Xem cấu hình" />}
                  </Button>
                  {canManageSchema && (
                    <Button
                      variant="outline"
                      className="h-7 text-xs"
                      aria-label={`Sửa cấu hình "${config.name}"`}
                      onClick={() => {
                        setForm(formFromConfig(config));
                        setEditingId(config.id);
                        setFormOpen(true);
                      }}
                    >
                      <Translated text="Sửa cấu hình" />
                    </Button>
                  )}
                  {config.review_status === 'pending_review' && canApproveMetrics && (
                    <Button variant="default" className="h-7 text-xs" onClick={() => void review(config.id, 'approve')}>
                      <Translated text="Duyệt" />
                    </Button>
                  )}
                  {config.review_status === 'pending_review' && canApproveMetrics && (
                    <Button variant="outline" className="h-7 text-xs" onClick={() => void review(config.id, 'reject')}>
                      <Translated text="Từ chối" />
                    </Button>
                  )}
                </div>
              </div>
              {expandedId === config.id && <ConfigDetails config={config} />}
              <ul className="mt-2 flex flex-wrap gap-2">
                {config.attributes.map((attribute) => (
                  <li key={attribute.id} className="flex items-center gap-2 rounded-full border border-border px-2 py-1 text-xs">
                    <span>
                      {attribute.label} <span className="text-muted-foreground">({attribute.data_type})</span>
                    </span>
                    {canManageSchema && config.review_status === 'approved' && attribute.data_type === 'number' && (
                      <Button
                        variant="ghost"
                        className="h-6 px-2 text-xs"
                        aria-label={`Tạo metric từ "${attribute.label}"`}
                        onClick={() => void createMetric(config.id, attribute)}
                      >
                        <Translated text="Tạo metric (SUM)" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
