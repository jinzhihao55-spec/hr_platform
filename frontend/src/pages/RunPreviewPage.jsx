import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  RefreshCw,
  Send,
} from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import WeeklyReviewPanel from '../components/run/WeeklyReviewPanel';
import { getPublishedReport } from '../services/reportService';
import {
  answerRunDecision,
  createRevisionRun,
  getRun,
  getRunPreview,
  getWeeklyReview,
  publishRun,
} from '../services/runService';
import './RunPreviewPage.css';

const KINDS = {
  daily: { label: '日报', action: '发布日报' },
  weekly: { label: '周报', action: '发布周报' },
};

function numericDelta(current, baseline) {
  if (typeof current !== 'number' || typeof baseline !== 'number') return '—';
  const delta = current - baseline;
  return delta > 0 ? `+${delta}` : String(delta);
}

function baselineLabel(periodEnd, version) {
  if (!periodEnd) return '未关联';
  const [year, month, day] = periodEnd.split('-').map(Number);
  return `${year}年${month}月${day}日${version ? ` v${version}` : ''}`;
}

function dailyRows(preview, baselineReport) {
  const current = preview?.rows || {};
  const publishedBaseline = baselineReport?.snapshot?.rows || {};
  const replayedBaseline = preview?.baseline_rows || {};
  const hasReplayedBaseline = Object.keys(replayedBaseline).length > 0;
  return Object.entries(current)
    .map(([number, row]) => {
      const baselineValue = hasReplayedBaseline
        ? replayedBaseline[number]
        : publishedBaseline[number]?.value;
      return {
        number: Number(number),
        label: row.label || '',
        baseline: row.is_blank ? '' : (baselineValue ?? '—'),
        current: row.is_blank ? '' : (row.value ?? '—'),
        delta: row.is_blank ? '' : numericDelta(row.value, baselineValue),
        blank: Boolean(row.is_blank),
      };
    })
    .sort((left, right) => left.number - right.number);
}

function targetFor(run, kind) {
  return (run?.targets || []).find((target) => target.report_kind === kind);
}

function blockingReason(preview) {
  const codes = preview?.validation_summary?.blocking_validation_codes || [];
  if (codes.includes('weekly_last_workday_only')) {
    return '周报仅在本周最后一个工作日发布；当前内容只用于过程预览。';
  }
  return '';
}

function failedCalculationValidations(run, reportKind) {
  return (run?.validations || []).filter((validation) => (
    validation.report_kind === reportKind
    && validation.severity === 'BLOCK'
    && validation.outcome !== 'PASS'
    && validation.validation_code !== 'weekly_last_workday_only'
  ));
}

export default function RunPreviewPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const activeKindTouched = useRef(false);
  const [run, setRun] = useState(null);
  const [previews, setPreviews] = useState({ daily: null, weekly: null });
  const [previewErrors, setPreviewErrors] = useState({ daily: '', weekly: '' });
  const [baselineReport, setBaselineReport] = useState(null);
  const [weeklyReview, setWeeklyReview] = useState({ items: [] });
  const [weeklyReviewError, setWeeklyReviewError] = useState('');
  const [activeKind, setActiveKind] = useState('daily');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [publishingKind, setPublishingKind] = useState('');
  const [reviewActionId, setReviewActionId] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const runData = await getRun(runId);
      setRun(runData);
      const baselineRequest = runData.baseline_report_id
        ? getPublishedReport(runData.baseline_report_id)
        : Promise.resolve(null);
      const baselineResultPromise = Promise.allSettled([baselineRequest])
        .then(([result]) => result);

      // Preview endpoints persist validation state for the same Run. Keep them
      // sequential to avoid concurrent MySQL writes while baseline reads continue.
      const [dailyResult] = await Promise.allSettled([
        getRunPreview(runId, 'daily'),
      ]);
      const [weeklyResult] = await Promise.allSettled([
        getRunPreview(runId, 'weekly'),
      ]);
      const baselineResult = await baselineResultPromise;
      setPreviews({
        daily: dailyResult.status === 'fulfilled' ? dailyResult.value : null,
        weekly: weeklyResult.status === 'fulfilled' ? weeklyResult.value : null,
      });
      setPreviewErrors({
        daily: dailyResult.status === 'rejected' ? dailyResult.reason.message : '',
        weekly: weeklyResult.status === 'rejected' ? weeklyResult.reason.message : '',
      });
      setBaselineReport(baselineResult.status === 'fulfilled' ? baselineResult.value : null);
      let reviewResult;
      try {
        reviewResult = await getWeeklyReview(runId);
        setWeeklyReview(reviewResult);
        setWeeklyReviewError('');
      } catch (reviewError) {
        reviewResult = { items: [] };
        setWeeklyReview(reviewResult);
        setWeeklyReviewError(reviewError.message || '周报复核明细加载失败');
      }
      const weeklyPreview = weeklyResult.status === 'fulfilled' ? weeklyResult.value : null;
      const weeklySummary = weeklyPreview?.validation_summary || {};
      const isFriday = new Date(`${runData.report_date}T12:00:00`).getDay() === 5;
      const weeklyNeedsAttention = Boolean(
        reviewResult.items?.length
        || weeklySummary.review_count
        || weeklySummary.block_count,
      );
      if (!activeKindTouched.current && isFriday && weeklyNeedsAttention) {
        setActiveKind('weekly');
      }
      try {
        setRun(await getRun(runId));
      } catch {
        setRun(runData);
      }
    } catch (requestError) {
      setError(requestError.message || '预览加载失败');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(
    () => dailyRows(previews.daily, baselineReport),
    [baselineReport, previews.daily],
  );

  const publish = async (kind) => {
    setPublishingKind(kind);
    setError('');
    setNotice('');
    try {
      const result = await publishRun(runId, [kind]);
      const report = result.reports?.find((item) => item.report_kind === kind);
      setRun((current) => ({
        ...current,
        targets: (current.targets || []).map((target) => (
          target.report_kind === kind
            ? { ...target, status: 'published', published_report_id: report?.id }
            : target
        )),
      }));
      if (kind === 'daily') {
        try {
          const weeklyPreview = await getRunPreview(runId, 'weekly');
          setPreviews((current) => ({ ...current, weekly: weeklyPreview }));
          setPreviewErrors((current) => ({ ...current, weekly: '' }));
        } catch (weeklyError) {
          setPreviewErrors((current) => ({
            ...current,
            weekly: weeklyError.message || '周报预览刷新失败',
          }));
        }
      }
      try {
        const refreshedRun = await getRun(runId);
        setRun({
          ...refreshedRun,
          targets: (refreshedRun.targets || []).map((target) => (
            target.report_kind === kind
              ? { ...target, status: 'published', published_report_id: report?.id }
              : target
          )),
        });
      } catch {
        // Keep the optimistic published target when refresh fails.
      }
      setNotice(`${KINDS[kind].label}已发布，报告版本已写入历史记录。`);
    } catch (requestError) {
      setError(requestError.message || `${KINDS[kind].label}发布失败`);
    } finally {
      setPublishingKind('');
    }
  };

  const confirmWeeklyReview = async (item, answer) => {
    setReviewActionId(item.decision_id);
    setError('');
    setNotice('');
    try {
      await answerRunDecision(
        runId,
        item.decision_id,
        item.resolution === 'select_top3_projects'
          ? answer
          : '确认按自然人计1人',
      );
      await load();
      setNotice('周报复核已确认，发布状态已重新计算。');
    } catch (requestError) {
      setError(requestError.message || '周报复核确认失败');
    } finally {
      setReviewActionId('');
    }
  };

  const createSameDayRevision = async () => {
    setReviewActionId('revision');
    setError('');
    try {
      const result = await createRevisionRun(run.report_date);
      navigate(`/runs/${result.run.id}`);
    } catch (requestError) {
      setError(requestError.message || '同日修订 Run 创建失败');
      setReviewActionId('');
    }
  };

  if (loading && !run) {
    return <main className="preview-page preview-page-state" role="status">正在计算日报与周报预览…</main>;
  }

  if (error && !run) {
    return (
      <main className="preview-page preview-page-state">
        <h1>预览无法打开</h1>
        <p>{error}</p>
        <button type="button" className="preview-secondary" onClick={load}>重新加载</button>
      </main>
    );
  }

  const activePreview = previews[activeKind];
  const baselineStale = run.baseline_status === 'stale';
  const activeError = previewErrors[activeKind];
  const activeBlockingReason = blockingReason(activePreview);
  const activeFailedCalculations = failedCalculationValidations(run, activeKind);
  const weeklyRows = previews.weekly?.main_rows || [];
  const supersededKinds = Object.entries(KINDS)
    .filter(([kind]) => targetFor(run, kind)?.status === 'superseded')
    .map(([, definition]) => definition.label);

  return (
    <main className="preview-page">
      <header className="preview-header">
        <div>
          <Link to={`/runs/${runId}`} className="back-link">
            <ArrowLeft aria-hidden="true" size={15} />返回输入与确认
          </Link>
          <h1>报表预览</h1>
          <p>
            {run.report_date} · 规则版本 {run.rule_version} · 基线{' '}
            {baselineLabel(run.baseline_period_end, run.baseline_version)}
          </p>
        </div>
        <div className="publish-actions" aria-label="独立发布">
          {Object.entries(KINDS).map(([kind, definition]) => {
            const preview = previews[kind];
            const target = targetFor(run, kind);
            const published = target?.status === 'published';
            const superseded = target?.status === 'superseded';
            const notDue = kind === 'weekly' && Boolean(blockingReason(preview));
            const disabled = (
              !preview?.publishable
              || published
              || superseded
              || baselineStale
              || Boolean(publishingKind)
            );
            const disabledReason = blockingReason(preview);
            return (
              <button
                type="button"
                key={kind}
                className={kind === 'daily' ? 'publish-primary' : 'preview-secondary'}
                disabled={disabled}
                aria-label={notDue ? definition.action : undefined}
                title={disabled ? (disabledReason || (notDue ? '未到本周最后一个工作日' : preview?.validation_summary?.blocking_validation_codes?.join('、') || '校验未通过')) : undefined}
                onClick={() => publish(kind)}
              >
                {publishingKind === kind
                  ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
                  : published || superseded
                    ? <CheckCircle2 aria-hidden="true" size={15} />
                    : <Send aria-hidden="true" size={15} />}
                {superseded
                  ? `${definition.label}已替代`
                  : published
                  ? `${definition.label}已发布`
                  : notDue
                    ? '未到周报日'
                    : definition.action}
              </button>
            );
          })}
        </div>
      </header>

      {error && <div className="preview-alert error" role="alert">{error}</div>}
      {notice && <div className="preview-alert success" role="status">{notice}</div>}
      {baselineStale && (
        <div className="preview-alert warning superseded-notice" role="alert">
          <CircleAlert aria-hidden="true" size={16} />
          <div>
            <strong>当前日报基线已过期</strong>
            <p>
              当前为 {baselineLabel(run.baseline_period_end, run.baseline_version)}；
              最新可用基线为 {baselineLabel(
                run.latest_baseline_period_end,
                run.latest_baseline_version,
              )}。本次运行不能继续发布。
            </p>
          </div>
          <button
            type="button"
            className="weekly-revision-action"
            disabled={Boolean(reviewActionId)}
            onClick={createSameDayRevision}
          >
            {reviewActionId === 'revision'
              ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
              : <RefreshCw aria-hidden="true" size={15} />}
            创建同日修订 Run
          </button>
        </div>
      )}
      {supersededKinds.length > 0 && (
        <div className="preview-alert warning superseded-notice" role="status">
          <RefreshCw aria-hidden="true" size={16} />
          <div>
            <strong>
              该 Run 的{supersededKinds.join('、')}已被同日后续版本替代。
            </strong>
            <p>历史版本保持只读；需要重新发布时请创建新的同日修订 Run。</p>
          </div>
          <button
            type="button"
            className="weekly-revision-action"
            disabled={Boolean(reviewActionId)}
            onClick={createSameDayRevision}
          >
            {reviewActionId === 'revision'
              ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
              : <RefreshCw aria-hidden="true" size={15} />}
            创建同日修订 Run
          </button>
        </div>
      )}

      <div className="preview-targets">
        {Object.entries(KINDS).map(([kind, definition]) => {
          const preview = previews[kind];
          const summary = preview?.validation_summary;
          const notDue = kind === 'weekly' && Boolean(blockingReason(preview));
          return (
            <button
              type="button"
              key={kind}
              aria-label={`${definition.label}预览`}
              className={activeKind === kind ? 'active' : ''}
              onClick={() => {
                activeKindTouched.current = true;
                setActiveKind(kind);
              }}
            >
              <span>{definition.label}</span>
              <strong className={preview?.publishable || notDue ? 'ready' : 'blocked'}>
                {preview?.publishable ? '校验通过' : notDue ? '过程预览' : '需要处理'}
              </strong>
              <small>
                {summary
                  ? `阻断 ${summary.block_count || 0} · 复核 ${summary.review_count || 0}`
                  : previewErrors[kind] || '正在加载'}
              </small>
            </button>
          );
        })}
      </div>

      {activeBlockingReason && (
        <div className="preview-alert warning" role="status">
          <CircleAlert aria-hidden="true" size={16} />
          {activeBlockingReason}
        </div>
      )}

      {activeFailedCalculations.length > 0 && (
        <div className="preview-alert error validation-details" role="alert">
          <CircleAlert aria-hidden="true" size={16} />
          <div>
            <strong>还有 {activeFailedCalculations.length} 项计算校验未通过</strong>
            <ul>
              {activeFailedCalculations.map((validation) => (
                <li key={validation.validation_code}>{validation.message}</li>
              ))}
            </ul>
            <p>请核对输入和日报链路；输入已冻结时请创建同日修订 Run。</p>
          </div>
        </div>
      )}

      {activeError ? (
        <section className="preview-empty" role="alert">
          <CircleAlert aria-hidden="true" size={19} />
          <div><h2>{KINDS[activeKind].label}暂不可预览</h2><p>{activeError}</p></div>
        </section>
      ) : activeKind === 'daily' ? (
        <section className="preview-table-section" aria-labelledby="daily-preview-title">
          <div className="preview-section-heading">
            <div><h2 id="daily-preview-title">日报 Row2–Row40</h2><p>基线来自上一份已发布日报；差异仅对数值行计算。</p></div>
            <code title={previews.daily?.snapshot_hash}>{previews.daily?.snapshot_hash?.slice(0, 12)}…</code>
          </div>
          <div className="preview-table-scroll">
            <table className="preview-table">
              <thead><tr><th>行</th><th>事项</th><th className="number">基线</th><th className="number">本次</th><th className="number">差异</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.number} className={row.blank ? 'blank' : ''}>
                    <td>Row{row.number}</td><td>{row.label}</td><td className="number">{row.baseline}</td><td className="number current">{row.current}</td><td className="number delta">{row.delta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <div className="weekly-preview-content">
          <WeeklyReviewPanel
            items={weeklyReview.items}
            error={weeklyReviewError}
            busyId={reviewActionId}
            onConfirm={confirmWeeklyReview}
            onCreateRevision={createSameDayRevision}
          />
          <section className="preview-table-section" aria-labelledby="weekly-preview-title">
            <div className="preview-section-heading">
              <div><h2 id="weekly-preview-title">周报 · 主体 × 事业部</h2><p>{activePreview?.period_start} 至 {activePreview?.period_end}</p></div>
              <code title={activePreview?.snapshot_hash}>{activePreview?.snapshot_hash?.slice(0, 12)}…</code>
            </div>
            <div className="preview-table-scroll">
              <table className="preview-table">
                <thead><tr><th>主体</th><th>事业部</th><th className="number">在职</th><th className="number">正式</th><th className="number">实习</th><th className="number">劳务</th><th className="number">入职</th><th className="number">离职</th></tr></thead>
                <tbody>
                  {weeklyRows.map((row, index) => (
                    <tr key={`${row.subject || ''}-${row.business_unit || index}`}>
                      <td>{row.subject || '—'}</td><td>{row.business_unit || '—'}</td><td className="number">{row.headcount ?? '—'}</td><td className="number">{row.cnt_formal ?? '—'}</td><td className="number">{row.cnt_intern ?? '—'}</td><td className="number">{row.cnt_labor ?? '—'}</td><td className="number">{row.joiners ?? '—'}</td><td className="number">{row.leavers ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
