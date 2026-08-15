import { useState } from 'react';
import { FileUp, LoaderCircle, AlertTriangle, CheckCircle } from 'lucide-react';
import { overrideDailyBaseline } from '../../services/runService';

function displayDate(value) {
  if (!value) return '未知日期';
  const [year, month, day] = value.split('-').map(Number);
  return `${year}年${month}月${day}日`;
}

export default function BaselineOverridePanel({ reportDate, onOverridden }) {
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const upload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setError('');
    setResult(null);
    try {
      const res = await overrideDailyBaseline(reportDate, file);
      setResult(res);
      await onOverridden(res);
    } catch (requestError) {
      setError(requestError.message || '基线覆盖上传失败');
    } finally {
      setImporting(false);
      event.target.value = '';
    }
  };

  return (
    <section className="baseline-override" aria-labelledby="baseline-override-title">
      <div className="baseline-override-heading">
        <div>
          <strong id="baseline-override-title">上传调整后基线</strong>
          <p>
            上传 {displayDate(reportDate)} 手动调整后的日报 xlsx，
            系统将覆盖该日数据并自动重算后续所有报表
          </p>
        </div>
      </div>

      {!result && !error && (
        <label className={`baseline-upload ${importing ? 'disabled' : ''}`}>
          {importing
            ? <LoaderCircle className="spin" aria-hidden="true" size={16} />
            : <FileUp aria-hidden="true" size={16} />}
          <span>{importing ? '正在上传并重算…' : '选择调整后的日报文件'}</span>
          <input
            type="file"
            aria-label="上传调整后的日报 xlsx 作为新基线"
            accept=".xlsx,.xls"
            disabled={importing}
            onChange={upload}
          />
        </label>
      )}

      {error && (
        <div className="baseline-override-error" role="alert">
          <AlertTriangle aria-hidden="true" size={16} />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="baseline-override-result">
          <div className="baseline-override-success">
            <CheckCircle aria-hidden="true" size={16} />
            <span>
              基线已覆盖
              {result.overwritten ? '（覆盖已有数据）' : '（首次导入）'}
            </span>
          </div>
          <dl className="baseline-override-kpis">
            <div>
              <dt>今日入职 (Row2)</dt>
              <dd>{result.kpis?.row2_今日入职 ?? '-'}</dd>
            </div>
            <div>
              <dt>今日离职 (Row3)</dt>
              <dd>{result.kpis?.row3_今日离职 ?? '-'}</dd>
            </div>
            <div>
              <dt>今日净增 (Row7)</dt>
              <dd>{result.kpis?.row7_今日净增 ?? '-'}</dd>
            </div>
            <div>
              <dt>MTD净增 (Row12)</dt>
              <dd>{result.kpis?.row12_MTD净增 ?? '-'}</dd>
            </div>
          </dl>
          {result.cascaded && result.cascaded.length > 0 && (
            <div className="baseline-override-cascade">
              <p>已级联重算 {result.cascaded.length} 个后续日报：</p>
              <ul>
                {result.cascaded.map((item) => (
                  <li key={item.report_date}>
                    {displayDate(item.report_date)}
                    {item.status === 'succeeded' ? (
                      <span className="cascade-ok">✓</span>
                    ) : (
                      <span className="cascade-fail" title={item.status}>
                        ✗ {item.status}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.cascade_error && (
            <div className="baseline-override-error" role="alert">
              <AlertTriangle aria-hidden="true" size={16} />
              <span>{result.cascade_error}</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}