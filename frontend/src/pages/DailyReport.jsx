import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, FileClock, LoaderCircle } from 'lucide-react';
import {
  downloadPublishedArtifact,
  getPublishedReport,
  getPublishedReports,
} from '../services';
import './DailyReport.css';

const KPI_ROWS = [
  { row: 2, label: '今日入职', detail: 'Row2' },
  { row: 3, label: '今日离职', detail: 'Row3' },
  { row: 7, label: '今日净增', detail: 'Row7' },
  { row: 12, label: 'MTD 净增', detail: 'Row12' },
];

function currentReports(items) {
  const current = items.filter((report) => report.is_current !== false);
  return current.length ? current : items;
}

function snapshotRows(detail) {
  const rows = detail?.snapshot?.rows || {};
  return Object.entries(rows)
    .map(([number, row]) => ({
      number: Number(number),
      label: row.label || '',
      value: row.is_blank ? '' : (row.value ?? '—'),
      blank: Boolean(row.is_blank),
    }))
    .sort((left, right) => left.number - right.number);
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function DailyReport() {
  const [reports, setReports] = useState([]);
  const [activeReportId, setActiveReportId] = useState('');
  const [detail, setDetail] = useState(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const requestSequence = useRef(0);

  useEffect(() => {
    let active = true;
    getPublishedReports('daily')
      .then((items) => {
        if (!active) return;
        const list = currentReports(Array.isArray(items) ? items : []);
        setReports(list);
        setActiveReportId(list[0]?.id || '');
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '日报历史加载失败');
      })
      .finally(() => {
        if (active) setListLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!activeReportId) return undefined;
    const sequence = ++requestSequence.current;
    setDetail(null);
    setDetailLoading(true);
    setError('');
    getPublishedReport(activeReportId)
      .then((data) => {
        if (requestSequence.current === sequence) setDetail(data);
      })
      .catch((requestError) => {
        if (requestSequence.current === sequence) {
          setError(requestError.message || '日报详情加载失败');
        }
      })
      .finally(() => {
        if (requestSequence.current === sequence) setDetailLoading(false);
      });
    return () => {
      if (requestSequence.current === sequence) requestSequence.current += 1;
    };
  }, [activeReportId]);

  const activeReport = reports.find((report) => report.id === activeReportId);
  const rows = useMemo(() => snapshotRows(detail), [detail]);
  const rowMap = useMemo(
    () => new Map(rows.map((row) => [row.number, row.value])),
    [rows],
  );
  const tenureRows = detail?.snapshot?.tenure?.rows || [];
  const validation = detail?.snapshot?.validation_summary;
  const downloadReady = Boolean(
    detail?.id && detail.id === activeReportId && !detailLoading && !downloading,
  );

  const selectReport = (reportId) => {
    if (reportId === activeReportId) return;
    requestSequence.current += 1;
    setDetail(null);
    setDetailLoading(true);
    setActiveReportId(reportId);
  };

  const download = async () => {
    if (!downloadReady) return;
    setDownloading(true);
    setError('');
    try {
      const blob = await downloadPublishedArtifact(detail.id, 'excel');
      saveBlob(blob, `员工数增减情况日报_${detail.period_end}_v${detail.version}.xlsx`);
    } catch (requestError) {
      setError(requestError.message || '日报下载失败');
    } finally {
      setDownloading(false);
    }
  };

  const openComputeLog = () => {
    sessionStorage.setItem('log-context', JSON.stringify({
      mode: 'daily',
      date: activeReport?.period_end,
    }));
    window.dispatchEvent(new CustomEvent('nav', { detail: 'log' }));
  };

  return (
    <main className="main published-report-page">
      <header className="head">
        <div>
          <h1>日报 · 员工数增减情况日报</h1>
          <div className="sub">
            报告日期 {activeReport?.period_end || '—'} · 不可变版本 v{activeReport?.version || '—'}
          </div>
        </div>
        <div className="head-btns">
          <button type="button" className="btn ghost" onClick={openComputeLog} disabled={!activeReport}>
            <FileClock aria-hidden="true" size={15} />计算日志
          </button>
          <button type="button" className="btn primary" onClick={download} disabled={!downloadReady}>
            {downloading ? <LoaderCircle className="spin" aria-hidden="true" size={15} /> : <Download aria-hidden="true" size={15} />}
            下载日报
          </button>
        </div>
      </header>

      {error && <div className="report-error" role="alert">{error}</div>}

      <div className="report-periods" aria-label="日报日期">
        {reports.map((report) => (
          <button
            type="button"
            key={report.id}
            className={activeReportId === report.id ? 'active' : ''}
            aria-label={`查看 ${report.period_end} 日报`}
            onClick={() => selectReport(report.id)}
          >
            {report.period_end}<small>v{report.version}</small>
          </button>
        ))}
      </div>

      {(listLoading || detailLoading) && (
        <div className="report-loading" role="status">
          <LoaderCircle className="spin" aria-hidden="true" size={18} />正在读取已发布日报
        </div>
      )}

      {!listLoading && reports.length === 0 && !error && (
        <div className="report-empty">暂无已发布日报。</div>
      )}

      {detail && (
        <>
          <section className="kpis" aria-label="日报关键指标">
            {KPI_ROWS.map((kpi) => (
              <article className="kpi" key={kpi.row}>
                <div className="l">{kpi.label}</div>
                <div className="v">{rowMap.get(kpi.row) ?? '—'}</div>
                <div className="dd">{kpi.detail}</div>
              </article>
            ))}
          </section>

          <div className="layout">
            <section className="card" aria-labelledby="daily-table-title">
              <div className="ch">
                <h2 id="daily-table-title">Sheet1 · 主表（Row2–Row40）</h2>
                <span className="meta">发布快照 {detail.id.slice(0, 8)}…</span>
              </div>
              <div className="cb">
                <div className="tblwrap">
                  <table className="tbl">
                    <thead><tr><th className="rn">行</th><th>事项</th><th className="r">报告值</th></tr></thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.number} className={row.blank ? 'blank' : ''}>
                          <td className="rn">{row.number}</td><td className="nm">{row.label}</td><td className="r">{row.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <div className="report-side-column">
              <section className="card">
                <div className="ch"><h2>在岗时长</h2><span className="meta">按事业部</span></div>
                <div className="cb">
                  <table className="tbl">
                    <thead><tr><th>事业部</th><th className="r">YTD离职</th><th className="r">平均年限</th></tr></thead>
                    <tbody>
                      {tenureRows.map((row, index) => (
                        <tr key={`${row.business_unit || 'total'}-${index}`}>
                          <td>{row.business_unit || row.bu || '合计'}</td><td className="r">{row.ytd_leavers ?? row.ytd ?? '—'}</td><td className="r">{row.avg_tenure_years ?? row.avg_year ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="card validation-summary">
                <div className="ch"><h2>发布校验</h2><span className="meta">发布时快照</span></div>
                <div className="cb">
                  <strong>{validation?.publishable ? '校验通过' : '需要复核'}</strong>
                  <span>阻断 {validation?.block_count ?? 0} · 复核 {validation?.review_count ?? 0}</span>
                </div>
              </section>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
