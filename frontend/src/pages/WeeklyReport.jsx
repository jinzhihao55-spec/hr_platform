import { useEffect, useRef, useState } from 'react';
import { Download, FileClock, LoaderCircle } from 'lucide-react';
import {
  downloadPublishedArtifact,
  getPublishedReport,
  getPublishedReports,
} from '../services';
import './WeeklyReport.css';

function currentReports(items) {
  const current = items.filter((report) => report.is_current !== false);
  return current.length ? current : items;
}

function projectText(projects) {
  if (!Array.isArray(projects)) return '—';
  return projects.map((project) => (
    typeof project === 'object'
      ? `${project.name || '未命名'}（${project.count ?? '—'}）`
      : String(project)
  )).join('、') || '—';
}

function saveBlob(blob, filename) {
  if (typeof URL.createObjectURL !== 'function') return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function WeeklyReport() {
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
    getPublishedReports('weekly')
      .then((items) => {
        if (!active) return;
        const list = currentReports(Array.isArray(items) ? items : []);
        setReports(list);
        setActiveReportId(list[0]?.id || '');
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '周报历史加载失败');
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
          setError(requestError.message || '周报详情加载失败');
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
  const mainRows = detail?.snapshot?.main_rows || [];
  const ccRows = detail?.snapshot?.cc_rows || [];
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
      saveBlob(blob, `员工数增减周报_${detail.period_start}_${detail.period_end}_v${detail.version}.xlsx`);
    } catch (requestError) {
      setError(requestError.message || '周报下载失败');
    } finally {
      setDownloading(false);
    }
  };

  const openComputeLog = () => {
    sessionStorage.setItem('log-context', JSON.stringify({
      mode: 'weekly',
      weekStart: activeReport?.period_start,
      weekEnd: activeReport?.period_end,
    }));
    window.dispatchEvent(new CustomEvent('nav', { detail: 'log' }));
  };

  return (
    <main className="main published-weekly-page">
      <header className="head">
        <div>
          <h1>周报 · 员工数增减周报</h1>
          <div className="sub">
            统计窗口 {activeReport?.period_start || '—'} ~ {activeReport?.period_end || '—'} · 不可变版本 v{activeReport?.version || '—'}
          </div>
        </div>
        <div className="weekly-head-actions">
          <button type="button" className="btn ghost" onClick={openComputeLog} disabled={!activeReport}>
            <FileClock aria-hidden="true" size={15} />计算日志
          </button>
          <button type="button" className="btn primary" onClick={download} disabled={!downloadReady}>
            {downloading ? <LoaderCircle className="spin" aria-hidden="true" size={15} /> : <Download aria-hidden="true" size={15} />}
            下载周报
          </button>
        </div>
      </header>

      {error && <div className="weekly-report-error" role="alert">{error}</div>}

      <div className="weekly-periods" aria-label="周报期间">
        {reports.map((report) => (
          <button
            type="button"
            key={report.id}
            className={activeReportId === report.id ? 'active' : ''}
            aria-label={`查看 ${report.period_start} 至 ${report.period_end} 周报`}
            onClick={() => selectReport(report.id)}
          >
            {report.period_start} ~ {report.period_end}<small>v{report.version}</small>
          </button>
        ))}
      </div>

      {(listLoading || detailLoading) && (
        <div className="weekly-report-loading" role="status">
          <LoaderCircle className="spin" aria-hidden="true" size={18} />正在读取已发布周报
        </div>
      )}

      {!listLoading && reports.length === 0 && !error && (
        <div className="weekly-report-loading">暂无已发布周报。</div>
      )}

      {detail && (
        <>
          <section className="weekly-summary-band" aria-label="周报发布摘要">
            <span><b>{mainRows.length}</b> 个事业部汇总</span>
            <span><b>{ccRows.length}</b> 个成本中心项目</span>
            <span className={validation?.publishable ? 'ok' : 'warning'}>
              {validation?.publishable ? '发布校验通过' : '发布快照需复核'}
            </span>
          </section>

          <section className="card" aria-labelledby="weekly-main-title">
            <div className="card-head">
              <h2 id="weekly-main-title">Sheet2 · 主体 × 事业部</h2>
              <span className="meta">在职拆分与本周人员变化</span>
            </div>
            <div className="card-body">
              <div className="tblwrap">
                <table className="tbl">
                  <thead><tr><th>主体</th><th>事业部</th><th className="r">在职</th><th className="r">正式</th><th className="r">实习</th><th className="r">劳务</th><th className="r">入职</th><th className="r">离职</th><th>前三大项目</th></tr></thead>
                  <tbody>
                    {mainRows.map((row, index) => (
                      <tr key={`${row.subject || ''}-${row.business_unit || index}`}>
                        <td>{row.subject || '—'}</td><td>{row.business_unit || '—'}</td><td className="r">{row.headcount ?? '—'}</td><td className="r">{row.cnt_formal ?? '—'}</td><td className="r">{row.cnt_intern ?? '—'}</td><td className="r">{row.cnt_labor ?? '—'}</td><td className="r">{row.joiners ?? '—'}</td><td className="r">{row.leavers ?? '—'}</td><td className="fx">{projectText(row.top3_projects)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="card" aria-labelledby="weekly-cc-title">
            <div className="card-head">
              <h2 id="weekly-cc-title">Sheet1 · 成本中心 × 项目</h2>
              <span className="meta">人数计数，不展示姓名名单</span>
            </div>
            <div className="card-body">
              <div className="tblwrap compact">
                <table className="tbl">
                  <thead><tr><th>成本中心</th><th>项目</th><th className="r">在职</th><th className="r">入职</th><th className="r">离职</th></tr></thead>
                  <tbody>
                    {ccRows.map((row, index) => (
                      <tr key={`${row.cost_center || ''}-${row.project || index}`}>
                        <td>{row.cost_center || '—'}</td><td>{row.project || '—'}</td><td className="r">{row.headcount ?? '—'}</td><td className="r">{row.joiners ?? '—'}</td><td className="r">{row.leavers ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
