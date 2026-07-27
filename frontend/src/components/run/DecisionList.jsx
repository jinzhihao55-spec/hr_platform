import { useState } from 'react';
import { CheckCircle2, LoaderCircle } from 'lucide-react';
import DecisionEvidence from './DecisionEvidence';

function optionLabel(option) {
  if (typeof option === 'string' || typeof option === 'number') return String(option);
  if (option && typeof option === 'object') {
    return String(option.label ?? option.value ?? option.answer ?? JSON.stringify(option));
  }
  return String(option ?? '确认');
}

function answerLabel(decision) {
  if (
    decision.decision_code === 'release_lwd_missing'
    && decision.answer?.last_working_day
  ) {
    return `最后工作日：${decision.answer.last_working_day}`;
  }
  if (
    decision.decision_code === 'recruitment_label_uncertain'
    && decision.answer
    && typeof decision.answer === 'object'
  ) {
    return '数值已补充';
  }
  return optionLabel(decision.answer);
}

function nonNegativeInteger(value) {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function ReleaseLwdForm({ decision, savingId, onAnswer }) {
  const [lastWorkingDay, setLastWorkingDay] = useState('');
  const saving = Boolean(savingId);
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(lastWorkingDay);

  const submit = (event) => {
    event.preventDefault();
    if (!valid || saving) return;
    onAnswer(decision, { last_working_day: lastWorkingDay });
  };

  return (
    <form className="release-lwd-form" onSubmit={submit}>
      <label>
        <span>最后工作日（LWD）</span>
        <input
          type="date"
          value={lastWorkingDay}
          disabled={saving}
          required
          onChange={(event) => setLastWorkingDay(event.target.value)}
        />
      </label>
      <div className="decision-options release-lwd-actions">
        <button type="submit" disabled={saving || !valid}>
          {savingId === decision.id && <LoaderCircle className="spin" size={14} />}
          确认最后工作日
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => onAnswer(decision, '替换输入')}
        >
          替换输入
        </button>
      </div>
    </form>
  );
}

function RecruitmentValueForm({ decision, savingId, onAnswer }) {
  const [previous, setPrevious] = useState('');
  const [current, setCurrent] = useState('');
  const previousValue = nonNegativeInteger(previous);
  const currentValue = nonNegativeInteger(current);
  const saving = Boolean(savingId);
  const valid = previousValue !== null && currentValue !== null;

  const submit = (event) => {
    event.preventDefault();
    if (!valid || saving) return;
    onAnswer(decision, {
      previous_month_offer_current_month_onboard: previousValue,
      current_month_offer_current_month_onboard: currentValue,
    });
  };

  return (
    <form className="recruitment-value-form" onSubmit={submit}>
      <label>
        <span>上月 Offer 当月预计入职</span>
        <input
          type="number"
          min="0"
          step="1"
          inputMode="numeric"
          value={previous}
          disabled={saving}
          onChange={(event) => setPrevious(event.target.value)}
        />
      </label>
      <label>
        <span>当月 Offer 当月预计入职</span>
        <input
          type="number"
          min="0"
          step="1"
          inputMode="numeric"
          value={current}
          disabled={saving}
          onChange={(event) => setCurrent(event.target.value)}
        />
      </label>
      <div className="decision-options recruitment-value-actions">
        <button type="submit" disabled={saving || !valid}>
          {savingId === decision.id && <LoaderCircle className="spin" size={14} />}
          补充数值
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => onAnswer(decision, '替换输入')}
        >
          替换输入
        </button>
      </div>
    </form>
  );
}

export default function DecisionList({ runId, decisions, savingId, onAnswer }) {
  const pendingDecisions = decisions.filter((decision) => decision.status !== 'answered');
  const batchableDecisions = pendingDecisions.filter(
    (decision) => !['release_lwd_missing', 'recruitment_label_uncertain'].includes(
      decision.decision_code,
    ),
  );
  const hasBatchable = batchableDecisions.length > 1;
  const evidenceRevision = decisions
    .map((decision) => `${decision.id}:${decision.status}:${JSON.stringify(decision.answer)}`)
    .join('|');

  if (!decisions?.length) {
    return (
      <div className="review-empty">
        <CheckCircle2 aria-hidden="true" size={18} />
        当前没有需要人工确认的项目。
      </div>
    );
  }

  return (
    <div className="decision-list">
      {hasBatchable && (
        <div className="batch-actions">
          <span>{batchableDecisions.length} 项可批量确认</span>
          <button type="button" className="batch-confirm-all"
            disabled={Boolean(savingId)}
            onClick={() => batchableDecisions.forEach(
              (decision) => onAnswer(decision, decision.options?.[0] || '确认'),
            )}
          >
            全部确认
          </button>
        </div>
      )}
      {decisions.map((decision, index) => {
        const answered = decision.status === 'answered';
        return (
          <article className={`decision-item ${answered ? 'answered' : ''}`} key={decision.id}>
            <div className="decision-number">{answered ? <CheckCircle2 size={17} /> : index + 1}</div>
            <div className="decision-content">
              <h3>{decision.question}</h3>
              <DecisionEvidence
                runId={runId}
                decision={decision}
                revision={evidenceRevision}
              />
              {answered ? (
                <p className="decision-answer">已确认：{answerLabel(decision)}</p>
              ) : decision.decision_code === 'release_lwd_missing' ? (
                <ReleaseLwdForm
                  decision={decision}
                  savingId={savingId}
                  onAnswer={onAnswer}
                />
              ) : decision.decision_code === 'recruitment_label_uncertain' ? (
                <RecruitmentValueForm
                  decision={decision}
                  savingId={savingId}
                  onAnswer={onAnswer}
                />
              ) : (
                <div className="decision-options">
                  {(decision.options || []).map((option) => {
                    const label = optionLabel(option);
                    return (
                      <button
                        type="button"
                        key={label}
                        disabled={Boolean(savingId)}
                        onClick={() => onAnswer(decision, option)}
                      >
                        {savingId === decision.id && <LoaderCircle className="spin" size={14} />}
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
              <details className="decision-meta-details">
                <summary>技术追踪信息</summary>
                <div className="decision-meta">
                  <span>{decision.decision_code}</span>
                  <span>{decision.fact_ref}</span>
                </div>
              </details>
            </div>
          </article>
        );
      })}
    </div>
  );
}
