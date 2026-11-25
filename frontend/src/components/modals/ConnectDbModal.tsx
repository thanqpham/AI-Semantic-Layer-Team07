'use client';

import React, { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  HardDrive,
  Loader2,
  ShieldCheck,
  Upload,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/context/AuthContext';
import {
  connectLiveTargetDb,
  convertRawSchemaToLayer,
  saveImportedSchema,
  updateLayer,
  uploadSqlDumpPreview,
  type LiveDbTlsOptions,
} from '@/lib/api';
import { getStoredToken } from '@/lib/jwt';
import { cn } from '@/lib/utils';
import { DbEngine, EngineIcon, engineLabels } from '@/components/workspace/shared';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

interface ConnectDbModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newDbName: string, dbId?: string) => void;
}

const engines: DbEngine[] = ['postgresql', 'mysql', 'sqlite', 'dump'];

const tlsModeOptions: Array<{ value: string; label: string }> = [
  { value: 'prefer', label: 'prefer ' },
  { value: 'disable', label: 'disable ' },
  { value: 'require', label: 'require ' },
  { value: 'verify_ca', label: 'verify_ca ' },
  { value: 'verify_full', label: 'verify_full ' },
];

const tlsSelectClass =
  'border-input h-9 w-full rounded-md border bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50';

interface TlsSettingsSectionProps {
  tlsMode: string;
  onTlsModeChange: (value: string) => void;
  onCaCert: (value: string) => void;
  onClientCert: (value: string) => void;
  onClientKey: (value: string) => void;
}

const TlsSettingsSection: React.FC<TlsSettingsSectionProps> = ({
  tlsMode,
  onTlsModeChange,
  onCaCert,
  onClientCert,
  onClientKey,
}) => {
  const readFile = (file: File | undefined, setter: (value: string) => void) => {
    if (!file) {
      setter('');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setter(String(reader.result ?? ''));
    reader.readAsText(file);
  };

  const showCa = tlsMode === 'verify_ca' || tlsMode === 'verify_full';
  const showClientPair = tlsMode === 'require' || showCa;

  return (
    <div>
      <Label htmlFor="tls-mode" className="mb-1.5 block text-sm">
        <Translated text={"Bảo mật kết nối (TLS)"} />
      </Label>
      <select
        id="tls-mode"
        value={tlsMode}
        onChange={(e) => onTlsModeChange(e.target.value)}
        className={tlsSelectClass}
      >
        {tlsModeOptions.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>

      {!showClientPair && (
        <p className="mt-1.5 text-xs text-destructive">
          <Translated text={"Kênh không được kiểm chứng chỉ — chỉ dùng cho dev/localhost"} />
        </p>
      )}

      {showCa && (
        <div className="mt-2">
          <Label htmlFor="tls-ca" className="mb-1.5 block text-sm">
            <Translated text={"Chứng chỉ CA (.pem/.crt)"} />
          </Label>
          <Input
            id="tls-ca"
            type="file"
            accept=".pem,.crt,.key"
            onChange={(e) => readFile(e.target.files?.[0], onCaCert)}
            className="cursor-pointer file:cursor-pointer"
          />
        </div>
      )}

      {showClientPair && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div>
            <Label htmlFor="tls-client-cert" className="mb-1.5 block text-sm">
              <Translated text={"Client certificate (.pem/.crt)"} />
            </Label>
            <Input
              id="tls-client-cert"
              type="file"
              accept=".pem,.crt,.key"
              onChange={(e) => readFile(e.target.files?.[0], onClientCert)}
              className="cursor-pointer file:cursor-pointer"
            />
          </div>
          <div>
            <Label htmlFor="tls-client-key" className="mb-1.5 block text-sm">
              <Translated text={"Client key (.key/.pem)"} />
            </Label>
            <Input
              id="tls-client-key"
              type="file"
              accept=".pem,.crt,.key"
              onChange={(e) => readFile(e.target.files?.[0], onClientKey)}
              className="cursor-pointer file:cursor-pointer"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export const ConnectDbModal: React.FC<ConnectDbModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { translate } = useLanguage();
  const { token } = useAuth();
  const [engine, setEngine] = useState<DbEngine>('postgresql');
  const [dbName, setDbName] = useState('');
  const [connUrl, setConnUrl] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState('');
  const [tlsMode, setTlsMode] = useState<string>('prefer');
  const [caCert, setCaCert] = useState('');
  const [clientCert, setClientCert] = useState('');
  const [clientKey, setClientKey] = useState('');
  const [dbUser, setDbUser] = useState('');
  const [dbPassword, setDbPassword] = useState('');

  const isDump = engine === 'dump';
  const tlsApplies = engine === 'postgresql' || engine === 'mysql';

  const resetForm = () => {
    setDbName('');
    setConnUrl('');
    setDescription('');
    setFile(null);
    setTlsMode('prefer');
    setCaCert('');
    setClientCert('');
    setClientKey('');
    setDbUser('');
    setDbPassword('');
    setError('');
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!dbName.trim()) return;

    setIsProcessing(true);
    setError('');
    const accessToken = token || getStoredToken();

    if (!accessToken) {
      setError('Vui lòng đăng nhập để lưu kết nối an toàn trên backend.');
      setIsProcessing(false);
      return;
    }

    try {
      if (isDump) {
        if (!file) {
          setError('Vui lòng chọn một tệp SQL dump.');
          setIsProcessing(false);
          return;
        }
        const preview = await uploadSqlDumpPreview(file, '', accessToken);
        const name = dbName.trim() || file.name.replace(/\.sql$/i, '');
        const savedRecord = await saveImportedSchema(name, preview, accessToken);
        const newLayer = convertRawSchemaToLayer(
          savedRecord.id,
          savedRecord.display_name || name,
          savedRecord.dialect || 'auto',
          savedRecord.raw_schema,
          undefined,
          savedRecord.updated_at,
          savedRecord.semantic_db_id,
          'sql_dump',
        );
        updateLayer(newLayer);
        onSuccess(name, newLayer.id);
        handleClose();
      } else {
        if (!connUrl.trim()) {
          setError('Vui lòng nhập chuỗi kết nối Database.');
          setIsProcessing(false);
          return;
        }
        const isVerify = tlsMode === 'verify_ca' || tlsMode === 'verify_full';
        if (tlsApplies && isVerify && !caCert) {
          setError('Cần nạp chứng chỉ CA cho mức verify');
          setIsProcessing(false);
          return;
        }
        if (tlsApplies && Boolean(clientCert) !== Boolean(clientKey)) {
          setError('Client certificate và key phải đi cùng nhau');
          setIsProcessing(false);
          return;
        }
        if (tlsApplies && Boolean(dbUser.trim()) !== Boolean(dbPassword.trim())) {
          setError('User và password phải đi cùng nhau');
          setIsProcessing(false);
          return;
        }
        const tls: LiveDbTlsOptions | undefined =
          tlsApplies && (tlsMode !== 'prefer' || caCert || clientCert || clientKey)
            ? {
                tls_mode: tlsMode,
                ...(caCert ? { ca_cert: caCert } : {}),
                ...(clientCert ? { client_cert: clientCert } : {}),
                ...(clientKey ? { client_key: clientKey } : {}),
              }
            : undefined;
        const dbType = engine === 'sqlite' ? 'sqlite' : engine === 'mysql' ? 'mysql' : 'auto';
        const connectOpts = tls || dbUser.trim() || dbPassword.trim()
          ? {
              tls,
              ...(dbUser.trim() ? { dbUser: dbUser.trim() } : {}),
              ...(dbPassword.trim() ? { dbPassword: dbPassword.trim() } : {}),
            }
          : undefined;
        const liveRecord = connectOpts
          ? await connectLiveTargetDb(dbName.trim(), dbType, connUrl.trim(), accessToken, connectOpts)
          : await connectLiveTargetDb(dbName.trim(), dbType, connUrl.trim(), accessToken);
        const newLayer = convertRawSchemaToLayer(
          liveRecord.id,
          liveRecord.display_name || dbName.trim(),
          liveRecord.dialect || dbType,
          liveRecord.raw_schema,
          undefined,
          liveRecord.updated_at,
          liveRecord.semantic_db_id,
          'live',
        );
        updateLayer(newLayer);
        onSuccess(dbName.trim(), newLayer.id);
        handleClose();
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : isDump
            ? 'Tải lên và trích xuất SQL dump thất bại'
            : 'Kết nối và trích xuất schema thất bại';
      setError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="bg-background sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl"><Translated text={"Connect a data source"} /></DialogTitle>
          <DialogDescription>
            <Translated text={"Point Optimus at a live database or upload a SQL dump. Credentials are read-only."} />
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {/* Engine Selector */}
          <div>
            <Label className="mb-2 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <Translated text={"Engine"} />
            </Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {engines.map((e) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEngine(e)}
                  className={cn(
                    'flex items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors cursor-pointer',
                    engine === e
                      ? 'border-primary bg-accent text-foreground font-semibold'
                      : 'border-border text-muted-foreground hover:text-foreground',
                  )}
                >
                  <EngineIcon engine={e} className="h-4 w-4 shrink-0" />
                  <span className="truncate text-xs">{engineLabels[e]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Connection Name */}
          <div>
            <Label htmlFor="db-name" className="mb-1.5 block text-sm">
              <Translated text={"Connection name"} />
            </Label>
            <Input
              id="db-name"
              value={dbName}
              onChange={(e) => setDbName(e.target.value)}
              placeholder={translate("e.g. E-Commerce Production DB")}
              required
            />
          </div>

          {/* Connection String or Dump Upload */}
          {!isDump ? (
            <div>
              <Label htmlFor="db-host" className="mb-1.5 block text-sm">
                <Translated text={"Host / connection string"} />
              </Label>
              <Input
                id="db-host"
                value={connUrl}
                onChange={(e) => setConnUrl(e.target.value)}
                placeholder="postgresql://localhost:5432/analytics"
                required
              />
              <p className="mt-1 text-xs text-muted-foreground">
                <Translated text={"URL chỉ gồm host:port/tên DB — nhập user & password vào ô riêng bên dưới."} />
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                <Translated text={"Đừng nhúng sslmode vào URL — cấu hình TLS ở mục bên dưới (tham số ssl trong URL sẽ bị loại bỏ)."} />
              </p>
            </div>
          ) : (
            <div>
              <Label htmlFor="db-file" className="mb-1.5 block text-sm">
                <Translated text={"Tệp SQL Dump (.sql)"} />
              </Label>
              <Input
                id="db-file"
                type="file"
                accept=".sql"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="cursor-pointer file:cursor-pointer"
                required
              />
            </div>
          )}

          {/* DB credentials — separate fields keep credentials out of the URL */}
          {tlsApplies && (
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <Label htmlFor="db-user" className="mb-1.5 block text-sm">
                  <Translated text={"Tên đăng nhập"} />
                </Label>
                <Input
                  id="db-user"
                  value={dbUser}
                  onChange={(e) => setDbUser(e.target.value)}
                  placeholder="Ví dụ: semantic_reader"
                  autoComplete="off"
                />
              </div>
              <div>
                <Label htmlFor="db-password" className="mb-1.5 block text-sm">
                  <Translated text={"Mật khẩu"} />
                </Label>
                <Input
                  id="db-password"
                  type="password"
                  value={dbPassword}
                  onChange={(e) => setDbPassword(e.target.value)}
                  placeholder="Nhập mật khẩu"
                  autoComplete="new-password"
                />
              </div>
            </div>
          )}

          {/* Description */}
          <div>
            <Label htmlFor="db-desc" className="mb-1.5 block text-sm">
              <Translated text={"Description"} />
            </Label>
            <Input
              id="db-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={translate("Mô tả mục đích hoặc nội dung của nguồn dữ liệu này")}
            />
          </div>

          {/* TLS Settings — only engines that support TLS */}
          {tlsApplies && (
            <TlsSettingsSection
              tlsMode={tlsMode}
              onTlsModeChange={setTlsMode}
              onCaCert={setCaCert}
              onClientCert={setClientCert}
              onClientKey={setClientKey}
            />
          )}

          {/* Guardrails Safety Box */}
          <div className="rounded-lg border border-border bg-secondary/30 p-3 text-xs">
            <div className="flex items-center gap-1.5 font-semibold text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="h-4 w-4" />
              <span><Translated text={"Bảo vệ an toàn dữ liệu:"} /></span>
            </div>
            <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted-foreground">
              <li><Translated text={"• Chỉ dành cho Live DB."} /></li>
              <li><Translated text={"• Truy vấn SELECT-only, được biên dịch deterministic."} /></li>
              <li><Translated text={"• Mặc định 100 dòng · Tối đa 1.000 dòng."} /></li>
              <li><Translated text={"• Timeout 15 giây."} /></li>
            </ul>
          </div>

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={handleClose}>
              <Translated text={"Hủy"} />
            </Button>
            <Button type="submit" disabled={!dbName.trim() || isProcessing} className="gap-1.5">
              {isProcessing && <Loader2 className="h-4 w-4 animate-spin" />}
              <Translated text={isProcessing
                ? 'Đang xử lý...'
                : isDump
                  ? 'Tải lên & Khởi tạo Schema'
                  : 'Bắt Đầu Kết Nối & Introspect'} />
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
