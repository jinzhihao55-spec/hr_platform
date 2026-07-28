import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  CircleAlert,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import RunStepper from '../components/run/RunStepper';
import BaselineImportPanel from '../components/run/BaselineImportPanel';
import SourceUploadGrid from '../components/run/SourceUploadGrid';
import {
  createRevisionRun,
  getRun,
  retryRun,
  uploadRunSource,
} from '../services/runService';
import RunReviewPage from './RunReviewPage';
import './RunWorkspacePage.css';

const STATUS_LABELS = {
  created: '待录入',
  parsing: '录入中',
  needs_review: '待确认',
  ready: '可预览',
  deduplicated: '已合并',
  failed: '处理失败',
};
const REQUIRED_SOURCE_COUNT = 4;
const IMAGE_FILE = /\.(?:bmp|jpe?g|png|tiff?|webp)$/i;

function displayDate(value) {
  if (!value) return '未指定日期';
  const [year, month, day] = value.split('-').map(Number);
  return `${year}年${month}月${day}日`;
}

function baselineLabel(periodEnd, version) {
  if (!periodEnd) return '未关联';
  return `${displayDate(periodEnd)}${version ? ` v${version}` : ''}`;
}

function shortHash(value) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '尚未冻结';
}

function publishedStatusLabel(targets = []) {
  const publishedKinds = new Set(
    targets
      .filter((target) => target.status === 'published')
      .map((target) => target.report_kind),
  );
  if (publishedKinds.has('daily') && publishedKinds.has('weekly')) return '日报/周报已发布';
  if (publishedKinds.has('daily')) return '日报已发布';
  if (publishedKinds.has('weekly')) return '周报已发布';
  return '';
}

export default function RunWorkspacePage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sourceErrors, setSourceErrors] = useState({});
  const [uploadingType, setUploadingType] = useState('');
  const [uploadNotice, setUploadNotice] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [creatingRevision, setCreatingRevision] = useState(false);
  const [baselineNotice, setBaselineNotice] = useState('');

  const loadRun = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setRun(await getRun(runId));
    } catch (requestError) {
      setError(requestError.message || '运行记录加载失败');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    loadRun();
  }, [loadRun]);

  const uploadedTypes = useMemo(
    () => new Set((run?.sources || []).map((source) => source.source_type)),
    [run?.sources],
  );
  const sourceCount = uploadedTypes.size;
  const baselineStale = run?.baseline_status === 'stale';
  const targetPublished = (run?.targets || []).some((target) => target.status === 'published');
  const publishedLabel = publishedStatusLabel(run?.targets);
  const initialBaselinePublished = Boolean(
    !run?.baseline_report_id
    && (run?.targets || []).some(
      (target) => target.report_kind === 'daily' && target.status === 'published',
    ),
  );
  const locked = Boolean(
    baselineStale
    || run?.source_bundle_hash
    || ['ready', 'deduplicated'].includes(run?.status)
    || run?.status === 'failed'
    || targetPublished,
  );

  const uploadSource = async (sourceType, file) => {
    setUploadingType(sourceType);
    setUploadNotice(
      file.type.startsWith('image/') || IMAGE_FILE.test(file.name)
        ? '图片识别处理中，可能需要 2-7 分钟。请勿重复上传或刷新页面。'
        : '',
    );
    setSourceErrors((current) => ({ ...current, [sourceType]: '' }));
    try {
      await uploadRunSource(runId, sourceType, file);
      await loadRun();
    } catch (requestError) {
      setSourceErrors((current) => ({
        ...current,
        [sourceType]: requestError.message || '上传失败，请检查文件结构',
      }));
    } finally {
      setUploadingType('');
      setUploadNotice('');
    }
  };

  const openReplacementInput = (decision) => {
    const sourceType = decision.fact_ref?.match(
      /^source:(personnel|resignation|release|recruitment):/,
    )?.[1];
    const input = sourceType ? document.getElementById(`source-${sourceType}`) : null;
    if (!input || input.disabled) {
      setError('无法打开对应输入，请刷新运行状态后重试');
      return;
    }
    setError('');
    input.click();
  };

  const retryFailedRun = async () => {
    setRetrying(true);
    setError('');
    try {
      await retryRun(runId);
      await loadRun();
    } catch (requestError) {
      setError(requestError.message || '重试失败，请检查系统状态');
    } finally {
      setRetrying(false);
    }
  };

  const createSameDayRevision = async () => {
    setCreatingRevision(true);
    setError('');
    try {
      const result = await createRevisionRun(run.report_date);
      navigate(`/runs/${result.run.id}`);
    } catch (requestError) {
      setError(requestError.message || '同日修订 Run 创建失败');
      setCreatingRevision(false);
    }
  };

  const baselineImported = async () => {
    setBaselineNotice('初始基线已建立，可从日历创建下一工作日运行');
    await loadRun();
  };

  if (loading && !run) {
    return <main className="run-page run-page-state" role="status">正在加载运行记录…</main>;
  }

  if (error && !run) {
    return (
      <main className="run-page run-page-state">
        <h1>运行记录无法打开</h1>
        <p>{error}</p>
        <button type="button" className="secondary-action" onClick={loadRun}>
          <RefreshCw aria-hidden="true" size={16} />重试
        </button>
      </main>
    );
  }

  return (
    <main className="run-page">
      <header className="run-header">
        <div>
          <Link className="back-link" to="/calendar">
            <ArrowLeft aria-hidden="true" size={15} />返回运行日历
          </Link>
          <div className="run-title-line">
            <h1>{displayDate(run.report_date)}</h1>
            <span className={`run-state-badge ${publishedLabel ? 'published' : run.status}`}>
              {publishedLabel || STATUS_LABELS[run.status] || run.status}
            </span>
          </div>
          <p>运行编号 {run.id}</p>
        </div>
        <button
          type="button"
          className="icon-button run-refresh"
          aria-label="刷新运行状态"
          title="刷新运行状态"
          onClick={loadRun}
          disabled={loading}
        >
          <RefreshCw className={loading ? 'spin' : ''} aria-hidden="true" size={17} />
        </button>
      </header>

      <RunStepper run={run} />

      {error && <div className="run-inline-error" role="alert">{error}</div>}
      {baselineNotice && <div className="run-inline-success" role="status">{baselineNotice}</div>}
      {baselineStale && (
        <div className="run-failure" role="alert">
          <CircleAlert aria-hidden="true" size={19} />
          <div>
            <strong>当前日报基线已过期</strong>
            <p>
              当前为 {baselineLabel(run.baseline_period_end, run.baseline_version)}；
              最新可用基线为 {baselineLabel(
                run.latest_baseline_period_end,
                run.latest_baseline_version,
              )}。请创建新的同日运行并重新上传四项输入。
            </p>
          </div>
          <button type="button" onClick={createSameDayRevision} disabled={creatingRevision}>
            <RefreshCw className={creatingRevision ? 'spin' : ''} aria-hidden="true" size={15} />
            创建同日修订 Run
          </button>
        </div>
      )}
      {run.status === 'failed' && (
        <div className="run-failure" role="alert">
          <CircleAlert aria-hidden="true" size={19} />
          <div>
            <strong>本次运行已停止</strong>
            <p>{run.error_message || run.error_code || '处理过程中发生错误，输入已暂时冻结。'}</p>
          </div>
          <button type="button" onClick={retryFailedRun} disabled={retrying}>
            <RotateCcw className={retrying ? 'spin' : ''} aria-hidden="true" size={15} />
            重试运行
          </button>
        </div>
      )}

      <div className="run-layout">
        <div className="run-primary-column">
          <section className="run-section" aria-labelledby="sources-title">
            <div className="run-section-heading">
              <div>
                <h2 id="sources-title">输入数据</h2>
                <p>每类数据必须从对应入口上传；系统不会根据文件名自动分配。</p>
              </div>
              <span className="source-count">{sourceCount} / {REQUIRED_SOURCE_COUNT} 已就绪</span>
            </div>
            {locked && !baselineStale && (
              <div className="input-lock-notice">
                <LockKeyhole aria-hidden="true" size={15} />
                <span>该运行的输入已冻结。如需更换文件，请创建同日修订 Run。</span>
                <button
                  type="button"
                  disabled={creatingRevision}
                  onClick={createSameDayRevision}
                >
                  <RefreshCw
                    className={creatingRevision ? 'spin' : ''}
                    aria-hidden="true"
                    size={14}
                  />
                  创建同日修订 Run
                </button>
              </div>
            )}
            {uploadNotice && (
              <div className="review-processing" role="status" aria-live="polite">
                <LoaderCircle className="spin" aria-hidden="true" size={16} />
                {uploadNotice}
              </div>
            )}
            <SourceUploadGrid
              sources={run.sources}
              decisions={run.decisions}
              errors={sourceErrors}
              uploadingType={uploadingType}
              locked={locked}
              onUpload={uploadSource}
            />
          </section>

          <RunReviewPage
            run={run}
            onRefresh={loadRun}
            onContinue={() => navigate(`/runs/${run.id}/preview`)}
            onReplaceInput={openReplacementInput}
          />
          {!run.baseline_report_id && !initialBaselinePublished && (
            <BaselineImportPanel run={run} onImported={baselineImported} />
          )}
        </div>

        <aside className="run-summary" aria-label="运行摘要">
          <div className="run-summary-heading">
            <ShieldCheck aria-hidden="true" size={18} />
            <h2>运行摘要</h2>
          </div>
          <dl>
            <div><dt>输入完整度</dt><dd>{sourceCount} / 4</dd></div>
            <div>
              <dt>日报基线</dt>
              <dd>
                {run.baseline_period_end
                  ? baselineLabel(run.baseline_period_end, run.baseline_version)
                  : run.baseline_report_id
                    ? '已关联'
                    : (initialBaselinePublished ? '本日初始基线' : '待建立')}
              </dd>
            </div>
            <div><dt>规则版本</dt><dd>{run.rule_version}</dd></div>
            <div><dt>尝试次数</dt><dd>{run.attempt_no ?? 0}</dd></div>
            <div><dt>输入指纹</dt><dd title={run.source_bundle_hash || ''}>{shortHash(run.source_bundle_hash)}</dd></div>
          </dl>
          <p>这里仅展示运行元数据，不回显人员字段值。</p>
        </aside>
      </div>
    </main>
  );
}
