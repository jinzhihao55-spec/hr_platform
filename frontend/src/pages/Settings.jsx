import { useState, useEffect } from 'react';
import { getConfig } from '../services';
import './Settings.css';

// 后端 /config 数据 → 前端卡片格式
function mapConfig(data) {
  if (!data) return [];

  const cards = [];

  // 员工类型纳入口径
  if (data.inclusion_types || data.exclusion_types) {
    cards.push({
      id: 'employee-type',
      title: '员工类型纳入口径',
      meta: '★ 硬阻断',
      type: 'pills',
      pills: {
        include: data.inclusion_types || [],
        exclude: data.exclusion_types || [],
      },
    });
  }

  // 离职方式 / 流程状态枚举
  if (data.resignation_active || data.resignation_passive) {
    const items = [
      ...(data.resignation_active || []).map((v) => ({ key: v, value: '→ Row4（主动）' })),
      ...(data.resignation_passive || []).map((v) => ({ key: v, value: '→ Row5 / Release' })),
    ];
    if (data.process_status_valid?.length) {
      items.push({ key: '流程状态·有效', value: data.process_status_valid.join(' / ') });
    }
    if (data.process_status_rejected?.length) {
      items.push({ key: '流程状态·剔除', value: data.process_status_rejected.join(' / ') });
    }
    cards.push({
      id: 'resign-type',
      title: '离职方式 / 流程状态枚举',
      meta: 'Row4/5/31 判定',
      type: 'kv',
      items,
    });
  }

  // OA 流程
  if (data.oa_release_flow_names || data.oa_release_flow_types) {
    cards.push({
      id: 'oa-flow',
      title: 'OA Release 流程定义',
      meta: 'Row5 识别',
      type: 'kv',
      items: [
        ...(data.oa_release_flow_names || []).map((v) => ({ key: '流程名', value: v })),
        ...(data.oa_release_flow_types || []).map((v) => ({ key: '流程类型', value: v })),
      ],
    });
  }

  // 公式链
  if (data.formula_chain) {
    const items = Object.entries(data.formula_chain).map(([k, v]) => ({ key: k, value: v }));
    cards.push({
      id: 'formula-chain',
      title: '公式链 / 校验规则',
      meta: items.length > 12 ? `发布前必过 · 共 ${items.length} 条，展示前 12 条` : '发布前必过',
      type: 'kv',
      items: items.slice(0, 12),
      mutedBody: true,
    });
  }

  // 员工类型分组
  if (data.type_bucket) {
    cards.push({
      id: 'type-bucket',
      title: '员工类型分组',
      meta: '在职 / 企聘 / 劳务',
      type: 'kv',
      items: Object.entries(data.type_bucket).map(([k, v]) => ({
        key: k,
        value: Array.isArray(v) ? v.join(', ') : String(v),
      })),
    });
  }

  // 事业部列表
  if (data.business_units) {
    cards.push({
      id: 'bu-list',
      title: '事业部列表',
      meta: '在岗时长 / 周报分组',
      type: 'kv',
      items: (Array.isArray(data.business_units) ? data.business_units : []).map((v) => ({
        key: v,
        value: '—',
      })),
    });
  }

  // 日报行定义
  if (data.daily_blank_rows || data.daily_header_rows || data.daily_derived_rows) {
    const items = [
      ...(data.daily_blank_rows || []).map((v) => ({ key: `Row${v}`, value: '空白行' })),
      ...(data.daily_derived_rows || []).map((v) => ({ key: `Row${v}`, value: '派生行' })),
    ];
    if (items.length > 0) {
      cards.push({
        id: 'daily-rows',
        title: '日报行定义',
        meta: '空白 / 派生 / 表头',
        type: 'kv',
        items,
      });
    }
  }

  return cards;
}

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [cards, setCards] = useState([]);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConfig();
      setCards(mapConfig(data));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <main className="main">
        <h1>口径与设置</h1>
        <div className="sub">正在加载…</div>
      </main>
    );
  }

  return (
    <main className="main">
      <div className="head">
        <div>
          <h1>口径与设置</h1>
          <div className="sub">
            确定性计算所依赖的字典与规则 · 由业务确认后纳入配置，禁止散落硬编码
          </div>
        </div>
        <button className="btn primary" onClick={loadConfig}>
          {loading ? '加载中…' : '刷新配置'}
        </button>
      </div>

      {error && <div className="card" style={{ marginBottom: 22 }}><div className="cb" style={{ color: 'var(--err)' }}>❌ {error}</div></div>}

      <div className="cfg">
        {cards.map((card) => (
          <div key={card.id} className="card">
            <div className="ch">
              <h2>{card.title}</h2>
              <span className="meta">{card.meta}</span>
            </div>
            <div className="cb">
              {card.type === 'pills' && (
                <>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>纳入</div>
                  <div className="pillset">
                    {card.pills.include.map((label, i) => (
                      <span key={i} className="p in">{label}</span>
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', margin: '12px 0 8px' }}>排除</div>
                  <div className="pillset">
                    {card.pills.exclude.map((label, i) => (
                      <span key={i} className="p ex">{label}</span>
                    ))}
                  </div>
                </>
              )}

              {card.type === 'kv' &&
                card.items.map((item, i) => (
                  <div key={i} className={`kv${card.mutedBody ? ' muted-body' : ''}`}>
                    <span className="k">{item.key}</span>
                    <span className={item.muted ? 'muted' : ''}>{item.value}</span>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
