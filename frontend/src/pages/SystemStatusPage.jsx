import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, CircleAlert, LoaderCircle, RefreshCw, Settings } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getReadiness } from '../services/reportService';
import './SystemStatusPage.css';

const COMPONENTS = [
  { key: 'mysql', label: 'MySQL 数据库', success: '连接正常', action: '检查数据库连接与凭据' },
  { key: 'redis', label: 'Redis 缓存', success: '连接正常', action: '检查 Redis 地址与服务状态' },
  { key: 'migration', label: '数据库结构', success: '迁移已完成', action: '运行数据库迁移' },
  { key: 'output', label: '产物目录', success: '可写', action: '检查输出目录权限' },
  { key: 'config', label: '生产配置', success: '必要变量完整', action: '补齐生产环境变量' },
];

export default function SystemStatusPage() {
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const check = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setPayload(await getReadiness());
    } catch (requestError) {
      if (requestError.data && typeof requestError.data === 'object') {
        setPayload(requestError.data);
      } else {
        setPayload(null);
        setError(requestError.message || '无法连接 API');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  const ready = payload?.status === 'ready';

  return (
    <main className="system-page">
      <header className="system-header">
        <div>
          <h1>系统状态</h1>
          <p>部署依赖、数据库迁移、产物目录与生产配置就绪检查。</p>
        </div>
        <button type="button" className="system-retry" onClick={check} disabled={loading}>
          {loading ? <LoaderCircle className="spin" aria-hidden="true" size={16} /> : <RefreshCw aria-hidden="true" size={16} />}
          重新检查
        </button>
      </header>

      {error && (
        <div className="system-connection-error" role="alert">
          <CircleAlert aria-hidden="true" size={18} />
          <div><strong>API 无法访问</strong><p>{error}</p></div>
        </div>
      )}

      <div className={`system-summary ${ready ? 'ready' : 'blocked'}`} role="status">
        {ready ? <CheckCircle2 aria-hidden="true" size={20} /> : <CircleAlert aria-hidden="true" size={20} />}
        <div>
          <strong>{ready ? '系统已就绪' : '系统尚未就绪'}</strong>
          <p>{ready ? '可以开始上传、预览与发布报表。' : '请先处理下方失败项，再执行正式报表任务。'}</p>
        </div>
      </div>

      <section className="system-grid" aria-label="就绪组件">
        {COMPONENTS.map((component) => {
          const ok = payload?.[component.key] === true;
          return (
            <article key={component.key} className={`system-component ${ok ? 'ok' : 'failed'}`}>
              {ok ? <CheckCircle2 aria-hidden="true" size={18} /> : <CircleAlert aria-hidden="true" size={18} />}
              <div>
                <h2>{component.label}</h2>
                <p>{ok ? component.success : component.action}</p>
              </div>
            </article>
          );
        })}
      </section>

      {payload?.config === false && (
        <Link className="system-settings-link" to="/settings">
          <Settings aria-hidden="true" size={15} />查看当前规则与配置
        </Link>
      )}
    </main>
  );
}
