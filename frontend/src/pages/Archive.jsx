import { useEffect, useMemo, useState } from 'react';
import { Download, FileText, LoaderCircle, Route } from 'lucide-react';
import { Link } from 'react-router-dom';
import { downloadPublishedArtifact, getPublishedReports } from '../services';
import './Archive.css';

const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'daily', label: '日报' },
  { value: 'weekly', label: '周报' },
];

function reportLabel(kind) {
  return kind === 'daily' ? '日报' : '周报';
}

function periodLabel(report) {
  return report.report_kind === 'daily'
    ? report.period_end
    : `${report.period_start} ~ ${report.period_end}`;
}

function publishedAt(value) {
  if (!value) return '—';
  return value.replace('T', ' ').slice(0, 16);
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

export default function Archive() {
  const [reports, setReports] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([getPublishedReports('daily'), getPublishedReports('weekly')])
      .then(([daily, weekly]) => {
        if (!active) return;
        const merged = [...(daily || []), ...(weekly || [])].sort((left, right) => (
          right.period_end.localeCompare(left.period_end)
          || right.version - left.version
        ));
        setReports(merged);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '发布历史加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const visibleReports = useMemo(
    () => reports.filter((report) => filter === 'all' || report.report_kind === filter),
    [filter, reports],
  );

  const download = async (report, artifactKind) => {
    const key = `${report.id}:${artifactKind}`;
    setDownloading(key);
    setError('');
    try {
      const blob = await downloadPublishedArtifact(report.id, artifactKind);
      const extension = artifactKind === 'excel' ? 'xlsx' : 'md';
      saveBlob(
        blob,
        `${reportLabel(report.report_kind)}_${periodLabel(report).replaceAll(' ~ ', '_')}_v${report.version}.${extension}`,
      );
    } catch (requestError) {
      setError(requestError.message || '产物下载失败');
    } finally {
      setDownloading('');
    }
  };

  return (
    <main className="archive-page">
      <header className="archive-header">
        <div>
          <h1>历史归档</h1>
          <p>按不可变报告版本查看正式发布记录与配套产物。</p>
        </div>
        <div className="archive-filters" aria-label="报告类型筛选">
          {FILTERS.map((option) => (
            <button
              type="button"
              key={option.value}
              className={filter === option.value ? 'active' : ''}
              onClick={() => setFilter(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      {error && <div className="archive-error" role="alert">{error}</div>}

      {loading ? (
        <div className="archive-state" role="status">
          <LoaderCircle className="spin" aria-hidden="true" size={18} />正在读取发布历史
        </div>
      ) : visibleReports.length === 0 ? (
        <div className="archive-state">暂无符合条件的发布记录。</div>
      ) : (
        <div className="archive-table-scroll">
          <table className="archive-table">
            <thead>
              <tr><th>类型</th><th>报告期间</th><th>版本</th><th>状态</th><th>发布时间</th><th>运行</th><th>产物</th></tr>
            </thead>
            <tbody>
              {visibleReports.map((report) => {
                const label = reportLabel(report.report_kind);
                return (
                  <tr key={report.id}>
                    <td><span className={`archive-kind ${report.report_kind}`}>{label}</span></td>
                    <td>{periodLabel(report)}</td>
                    <td>v{report.version}</td>
                    <td><span className={`archive-current ${report.is_current ? 'current' : ''}`}>{report.is_current ? '当前版本' : '已替代'}</span></td>
                    <td>{publishedAt(report.published_at)}</td>
                    <td>
                      <Link className="archive-run-link" to={`/runs/${report.run_id}`} title="查看运行">
                        <Route aria-hidden="true" size={15} />查看
                      </Link>
                    </td>
                    <td>
                      <div className="archive-actions">
                        <button
                          type="button"
                          aria-label={`下载${label} Excel`}
                          title="下载 Excel"
                          disabled={Boolean(downloading)}
                          onClick={() => download(report, 'excel')}
                        >
                          {downloading === `${report.id}:excel` ? <LoaderCircle className="spin" size={14} /> : <Download size={14} />}
                          Excel
                        </button>
                        <button
                          type="button"
                          aria-label={`下载${label} 执行说明`}
                          title="下载执行说明"
                          disabled={Boolean(downloading)}
                          onClick={() => download(report, 'execution_log')}
                        >
                          {downloading === `${report.id}:execution_log` ? <LoaderCircle className="spin" size={14} /> : <FileText size={14} />}
                          执行说明
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
