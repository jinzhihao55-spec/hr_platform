import { useMemo, useState } from 'react';
import { FileUp, LoaderCircle } from 'lucide-react';
import { finalizeRunBaseline } from '../../services/runService';

export default function BaselineImportPanel({ run, onImported }) {
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const sourceTypes = useMemo(
    () => new Set((run?.sources || []).map((source) => source.source_type)),
    [run?.sources],
  );
  const pendingCount = (run?.decisions || []).filter(
    (decision) => decision.status !== 'answered',
  ).length;
  const ready = sourceTypes.size === 4 && pendingCount === 0;

  const upload = async (event) => {
    const file = event.target.files?.[0];
    if (!file || !ready) return;
    setImporting(true);
    setError('');
    try {
      await finalizeRunBaseline(run.id, file);
      await onImported();
    } catch (requestError) {
      setError(requestError.message || '初始基线建立失败');
    } finally {
      setImporting(false);
      event.target.value = '';
    }
  };

  return (
    <section className="baseline-import" aria-labelledby="baseline-import-title">
      <div>
        <strong id="baseline-import-title">建立初始基线</strong>
        <p>{ready ? `上传 ${run.report_date} 的已验收日报` : '先完成四项输入和全部人工确认'}</p>
      </div>
      <label className={`baseline-upload ${importing || !ready ? 'disabled' : ''}`}>
        {importing
          ? <LoaderCircle className="spin" aria-hidden="true" size={16} />
          : <FileUp aria-hidden="true" size={16} />}
        <span>{importing ? '正在建立基线' : '上传本日定稿'}</span>
        <input
          type="file"
          aria-label="上传本日已验收日报并建立初始基线"
          accept=".xlsx,.xls"
          disabled={importing || !ready}
          onChange={upload}
        />
      </label>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
