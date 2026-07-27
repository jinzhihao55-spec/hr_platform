import { useEffect, useState } from 'react';
import { ChevronDown, LoaderCircle, ShieldCheck, TriangleAlert } from 'lucide-react';
import { getDecisionPreview } from '../../services/runService';

const VALUE_LABELS = {
  include: '计入',
  exclude: '不计入',
  review: '待确认',
  unreviewed: '待确认',
  confirmed: '已确认',
};

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.length ? value.join('、') : '—';
  return VALUE_LABELS[value] || String(value);
}

export default function DecisionEvidence({ runId, decision, revision }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (decision.decision_code !== 'ocr_review_required') return undefined;
    let active = true;
    setError('');
    getDecisionPreview(runId, decision.id)
      .then((result) => {
        if (active) setPreview(result);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '识别结果加载失败');
      });
    return () => {
      active = false;
    };
  }, [decision.decision_code, decision.id, revision, runId]);

  if (decision.decision_code !== 'ocr_review_required') return null;

  const answered = decision.status === 'answered';
  const sourceTitle = preview?.source_type === 'recruitment' ? '招聘' : 'OA/Release';
  return (
    <details className="decision-evidence" open={!answered}>
      <summary>
        <span>
          <ShieldCheck aria-hidden="true" size={15} />
          {answered ? '查看识别结果' : '识别结果'}
        </span>
        <ChevronDown aria-hidden="true" size={15} />
      </summary>
      <div className="decision-evidence-body">
        {!preview && !error && (
          <div className="decision-evidence-state" role="status">
            <LoaderCircle className="spin" aria-hidden="true" size={15} />
            正在读取结构化结果…
          </div>
        )}
        {error && (
          <div className="decision-evidence-state error" role="alert">
            <TriangleAlert aria-hidden="true" size={15} />
            {error}
          </div>
        )}
        {preview && (
          <>
            <div className="decision-evidence-scroll">
              <table aria-label={`${sourceTitle} 识别结果`}>
                <thead>
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column.key}>{column.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, index) => (
                    <tr key={row.source_row_no ?? index}>
                      {preview.columns.map((column) => (
                        <td key={column.key}>{formatValue(row[column.key])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(preview.warnings || []).map((warning) => (
              <p className="decision-evidence-warning" key={warning}>{warning}</p>
            ))}
          </>
        )}
      </div>
    </details>
  );
}
