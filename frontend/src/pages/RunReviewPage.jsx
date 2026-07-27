import { useMemo, useState } from 'react';
import { ArrowRight, CircleAlert, LoaderCircle } from 'lucide-react';
import DecisionList from '../components/run/DecisionList';
import { answerRunDecision } from '../services/runService';

export default function RunReviewPage({ run, onRefresh, onContinue, onReplaceInput }) {
  const [savingId, setSavingId] = useState('');
  const [error, setError] = useState('');
  const decisions = run?.decisions || [];
  const inputDecisions = decisions.filter((decision) => decision.report_kind !== 'weekly');
  const pending = inputDecisions.filter((decision) => decision.status !== 'answered');
  const weeklyPending = decisions.filter(
    (decision) => decision.report_kind === 'weekly' && decision.status !== 'answered',
  );
  const blockingValidations = useMemo(
    () => (run?.validations || []).filter(
      (item) => {
        if (item.report_kind === 'weekly') return false;
        const severity = String(item.severity || '').toLowerCase();
        const outcome = String(item.outcome || '').toLowerCase();
        return (
          ['block', 'blocker'].includes(severity)
          && !['pass', 'passed'].includes(outcome)
        );
      },
    ),
    [run?.validations],
  );
  const baselineMissing = !run?.baseline_report_id;
  const initialBaselinePublished = Boolean(
    baselineMissing
    && (run?.targets || []).some(
      (target) => target.report_kind === 'daily' && target.status === 'published',
    ),
  );
  const canContinue = (
    run?.status === 'ready'
    && pending.length === 0
    && blockingValidations.length === 0
  );

  const answerDecision = async (decision, answer) => {
    if (answer === '替换输入') {
      onReplaceInput?.(decision);
      return;
    }
    setSavingId(decision.id);
    setError('');
    try {
      await answerRunDecision(run.id, decision.id, answer);
      await onRefresh();
    } catch (requestError) {
      setError(requestError.message || '确认失败，请重试');
    } finally {
      setSavingId('');
    }
  };

  let blockReason = '';
  if (pending.length) blockReason = `还有 ${pending.length} 项需要确认`;
  else if (blockingValidations.length) blockReason = '仍有阻断校验未通过';
  else if (initialBaselinePublished) blockReason = '本日已作为初始基线发布';
  else if (baselineMissing) blockReason = '缺少上一份已发布日报基线';
  else if (run?.status !== 'ready') blockReason = '等待四项输入完成解析';

  return (
    <section
      className="run-section review-section"
      aria-labelledby="review-title"
      aria-busy={Boolean(savingId)}
    >
      <div className="run-section-heading">
        <div>
          <h2 id="review-title">人工确认</h2>
          <p>系统无法从输入确定的事实必须在这里补充或确认，回答后重新读取整条运行记录。</p>
        </div>
        <span className={`review-count ${pending.length ? 'pending' : ''}`}>
          {pending.length ? `${pending.length} 项待确认` : '无需确认'}
        </span>
      </div>

      {error && <div className="run-inline-error" role="alert">{error}</div>}
      {savingId && (
        <div className="review-processing" role="status" aria-live="polite">
          <LoaderCircle className="spin" aria-hidden="true" size={16} />
          正在确认并冻结本次输入，真实数据量较大时可能需要约一分钟。
        </div>
      )}
      {weeklyPending.length > 0 && (
        <div className="weekly-review-handoff" role="status">
          <CircleAlert aria-hidden="true" size={16} />
          <div>
            <strong>周报还有 {weeklyPending.length} 项待复核</strong>
            <p>进入报表预览后处理；这些项目不影响日报预览和发布。</p>
          </div>
        </div>
      )}
      <DecisionList
        runId={run.id}
        decisions={inputDecisions}
        savingId={savingId}
        onAnswer={answerDecision}
      />

      <div className="review-actions">
        {blockReason && (
          <span className="review-block-reason">
            <CircleAlert aria-hidden="true" size={15} />
            {blockReason}
          </span>
        )}
        <button
          type="button"
          className="primary-action"
          disabled={!canContinue}
          title={blockReason || undefined}
          aria-label={blockReason ? `无法预览：${blockReason}` : '预览日报与周报'}
          onClick={onContinue}
        >
          预览日报与周报
          <ArrowRight aria-hidden="true" size={16} />
        </button>
      </div>
    </section>
  );
}
