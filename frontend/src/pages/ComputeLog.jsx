import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import TraceItem from '../components/TraceItem/TraceItem';
import CheckItem from '../components/CheckItem/CheckItem';
import { getDailyDates, getDailyView, getWeeklyWeeks, getWeeklyView } from '../services';
import './ComputeLog.css';

// 某一行相关校验的真实结果：✗ 有失败 / ✓ 全通过 / — 无相关校验
function rowCheckField(rowNum, validations) {
  const rowRe = new RegExp(`Row${rowNum}(?!\\d)`);
  const related = (validations || []).filter(
    (c) => typeof c === 'object' && typeof c.check === 'string' && rowRe.test(c.check)
  );
  if (related.length === 0) return { label: '校验', value: '—', plain: true };
  const failed = related.filter((c) => !c.passed);
  if (failed.length > 0) {
    return { label: '校验', value: `✗ 未通过：${failed.map((c) => c.check).join('；')}`, plain: true };
  }
  return { label: '校验', value: '✓ 通过', ok: true, plain: true };
}

function mapDailyTraces(viewData) {
  const validations = viewData?.checks || viewData?.validations || [];
  return (viewData?.rows || []).map((r) => ({
    id: `row-${r.row}`,
    row: `Row${r.row}`,
    title: r.item || r.name || r.label || r.title || '',
    value: String(r.value ?? r.report ?? '—'),
    derive: r.derived || r.type === 'derive' || r.is_derived || false,
    open: false,
    fields: [
      { label: '输入源', value: r.source || r.公式 || r.formula || '—', plain: true },
      { label: '公式', value: r.formula || r.公式 || r.calc || '—' },
      { label: '最终值', value: String(r.value ?? r.report ?? '—') },
      rowCheckField(r.row, validations),
    ],
  }));
}

function mapWeeklyTraces(viewData) {
  const buTraces = (viewData?.traces || []).map((t, i) => ({
    id: `bu-${t.ref || i}`,
    row: 'Sheet2',
    title: `${t.ref || '事业部'}`,
    value: String(t.headcount ?? '—'),
    derive: false,
    open: false,
    fields: [
      { label: '在职总数', value: String(t.headcount ?? '—'), plain: true },
      {
        label: '类型拆分(正式/实习/劳务)',
        value: Array.isArray(t.split) ? t.split.join(' / ') : '—',
        plain: true,
      },
      { label: '本周入职', value: String(t.joiners ?? '—'), plain: true },
      { label: '本周离职', value: String(t.leavers ?? '—'), plain: true },
      {
        label: '前三项目',
        value: (t.top3 || []).map((p) => `${p.name}(${p.count})`).join('、') || '—',
        plain: true,
      },
    ],
  }));

  const ccTraces = (viewData?.cc_traces || []).map((t, i) => ({
    id: `cc-${t.ref || i}`,
    row: 'Sheet1',
    title: `${t.project || t.ref || '项目'}`,
    value: String(t.headcount ?? '—'),
    derive: false,
    open: false,
    fields: [
      { label: '成本中心', value: t.cost_center || '—', plain: true },
      { label: '在职人数', value: String(t.headcount ?? '—'), plain: true },
      { label: '本周入职', value: String(t.joiners ?? '—'), plain: true },
      { label: '本周离职', value: String(t.leavers ?? '—'), plain: true },
    ],
  }));

  return [...buTraces, ...ccTraces];
}

function mapChecks(viewData) {
  return (viewData?.checks || viewData?.validations || []).map((c) => ({
    label: typeof c === 'string' ? c : c.message || c.name || c.label || c.check,
    hard: typeof c === 'object' ? c.hard_block || c.hard || false : false,
    passed: typeof c === 'object' ? (c.passed ?? true) : true,
  }));
}

function findWeeklyIdx(options, weekStart, weekEnd) {
  if (!weekStart || !weekEnd) return -1;
  return options.findIndex(
    (o) => o.weekStart === weekStart && o.weekEnd === weekEnd
  );
}

export default function ComputeLog() {
  const navigate = useNavigate();
  const [mode, setMode] = useState('daily');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reportOptions, setReportOptions] = useState([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [viewData, setViewData] = useState(null);

  const loadDailyOptions = useCallback(async (preferDate) => {
    const data = await getDailyDates();
    const raw = Array.isArray(data) ? data : data?.dates || [];
    const list = raw.map((d) => (typeof d === 'string' ? d : d.report_date || d.date || ''));
    const options = list.map((d) => ({ key: d, label: `日报 ${d}`, date: d }));
    setReportOptions(options);
    if (options.length === 0) {
      setViewData(null);
      setLoading(false);
      return;
    }
    const idx = preferDate ? options.findIndex((o) => o.date === preferDate) : 0;
    setActiveIdx(idx >= 0 ? idx : 0);
  }, []);

  const loadWeeklyOptions = useCallback(async (preferStart, preferEnd) => {
    const data = await getWeeklyWeeks();
    const raw = Array.isArray(data) ? data : data?.weeks || [];
    const options = raw.map((w) => ({
      key: `${w.week_start || w.start}_${w.week_end || w.end}`,
      label: `周报 ${w.week_start || w.start} ~ ${w.week_end || w.end}`,
      weekStart: w.week_start || w.start,
      weekEnd: w.week_end || w.end,
    }));
    setReportOptions(options);
    if (options.length === 0) {
      setViewData(null);
      setLoading(false);
      return;
    }
    const idx = findWeeklyIdx(options, preferStart, preferEnd);
    setActiveIdx(idx >= 0 ? idx : 0);
  }, []);

  const loadDailyView = async (date) => {
    if (!date) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getDailyView(date);
      setViewData(data);
    } catch (err) {
      setError(err.message);
      setViewData(null);
    } finally {
      setLoading(false);
    }
  };

  const loadWeeklyView = async (weekStart, weekEnd) => {
    if (!weekStart || !weekEnd) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getWeeklyView(weekStart, weekEnd);
      setViewData(data);
    } catch (err) {
      setError(err.message);
      setViewData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      setError(null);
      let nav = null;
      const stored = sessionStorage.getItem('log-context');
      if (stored) {
        try {
          nav = JSON.parse(stored);
          sessionStorage.removeItem('log-context');
        } catch {
          /* ignore */
        }
      }
      try {
        if (nav?.mode === 'weekly') {
          setMode('weekly');
          await loadWeeklyOptions(nav.weekStart, nav.weekEnd);
        } else {
          setMode('daily');
          await loadDailyOptions(nav?.date);
        }
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };
    init();
  }, [loadDailyOptions, loadWeeklyOptions]);

  useEffect(() => {
    const opt = reportOptions[activeIdx];
    if (!opt) return;
    if (mode === 'weekly') {
      loadWeeklyView(opt.weekStart, opt.weekEnd);
    } else {
      loadDailyView(opt.date);
    }
  }, [reportOptions, activeIdx, mode]);

  const switchMode = async (nextMode) => {
    if (nextMode === mode) return;
    setMode(nextMode);
    setViewData(null);
    setActiveIdx(0);
    setLoading(true);
    setError(null);
    try {
      if (nextMode === 'weekly') {
        await loadWeeklyOptions();
      } else {
        await loadDailyOptions();
      }
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const traces = useMemo(
    () => (mode === 'weekly' ? mapWeeklyTraces(viewData) : mapDailyTraces(viewData)),
    [viewData, mode]
  );
  const checks = useMemo(() => mapChecks(viewData), [viewData]);
  const activeReport = reportOptions[activeIdx];

  const subTitle = mode === 'weekly'
    ? `周报 ${viewData?.week_start || activeReport?.weekStart || ''} ~ ${viewData?.week_end || activeReport?.weekEnd || ''} · Sheet2/Sheet1 逐行 trace`
    : `日报 ${activeReport?.date || ''} · Row2–40 / 在岗时长 trace`;

  const footnote = mode === 'weekly'
    ? '周报 trace 按事业部（Sheet2）与成本中心×项目（Sheet1）展示；完整 md 日志见当周最后工作日的日报计算日志。'
    : '完整日志覆盖 Row2–Row40（空白行标注"空白行-不填"）、在岗时长逐 BU、12 项校验与全部人工决策留痕。';

  if (loading && !viewData && reportOptions.length === 0 && !error) {
    return (
      <main className="main compute-log-page">
        <h1>计算日志</h1>
        <div className="sub">正在加载…</div>
      </main>
    );
  }

  return (
    <main className="main compute-log-page">
      <div className="head">
        <div>
          <h1>计算日志</h1>
          <div className="sub">{subTitle}</div>
        </div>
        <button
          className="btn ghost"
          onClick={() => navigate(mode === 'weekly' ? '/reports/weekly' : '/reports/daily')}
        >
          {mode === 'weekly' ? '← 返回周报' : '← 返回日报'}
        </button>
      </div>

      {error && (
        <div className="card" style={{ marginBottom: 22 }}>
          <div className="cb" style={{ color: 'var(--err)' }}>❌ {error}</div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 22 }}>
        <div className="cb" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span className="muted" style={{ fontSize: '12.5px' }}>报表类型：</span>
          <div className="seg">
            <a
              href="#"
              className={mode === 'daily' ? 'on' : ''}
              onClick={(e) => { e.preventDefault(); switchMode('daily'); }}
            >
              日报
            </a>
            <a
              href="#"
              className={mode === 'weekly' ? 'on' : ''}
              onClick={(e) => { e.preventDefault(); switchMode('weekly'); }}
            >
              周报
            </a>
          </div>
        </div>
      </div>

      {reportOptions.length > 0 && (
        <div className="card" style={{ marginBottom: 22 }}>
          <div className="cb" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span className="muted" style={{ fontSize: '12.5px' }}>选择报表：</span>
            <div className="seg">
              {reportOptions.map((opt, i) => (
                <a
                  key={opt.key}
                  className={activeIdx === i ? 'on' : ''}
                  href="#"
                  onClick={(e) => { e.preventDefault(); setActiveIdx(i); }}
                >
                  {opt.label}
                </a>
              ))}
            </div>
          </div>
        </div>
      )}

      {reportOptions.length === 0 && !loading && (
        <div className="card" style={{ marginBottom: 22 }}>
          <div className="cb muted">暂无已生成的{mode === 'weekly' ? '周报' : '日报'}，请先在工作台生成。</div>
        </div>
      )}

      <div className="compute-log-layout">
        <div className="card">
          <div className="ch">
            <h2>逐行计算 trace</h2>
            <span className="meta">点击展开每一行的取数与算法</span>
          </div>
          <div className="cb">
            {loading && <p className="muted" style={{ textAlign: 'center', padding: 12 }}>加载中…</p>}
            {!loading && traces.length === 0 && (
              <p className="muted" style={{ textAlign: 'center', padding: 20 }}>暂无计算日志数据</p>
            )}
            {traces.map((trace) => (
              <TraceItem
                key={trace.id}
                row={trace.row}
                title={trace.title}
                value={trace.value}
                derive={trace.derive}
                open={trace.open}
                fields={trace.fields}
              />
            ))}
            <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>{footnote}</p>
          </div>
        </div>

        <div className="card">
          <div className="ch">
            <h2>校验清单</h2>
            <span className="meta">
              {checks.filter((c) => c.passed).length} / {checks.length} 通过
            </span>
          </div>
          <div className="cb">
            {checks.length === 0 && (
              <p className="muted" style={{ fontSize: 12 }}>暂无校验项</p>
            )}
            {checks.map((check, i) => (
              <CheckItem key={i} label={check.label} hard={check.hard} passed={check.passed} />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
