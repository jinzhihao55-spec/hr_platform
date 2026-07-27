import {
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react';
import { useState } from 'react';

const DIMENSION_LABELS = {
  business_unit_no: '事业部编号',
  business_unit: '事业部',
  project_no: '项目编号',
  project_name: '项目名称',
  employee_type: '员工类型',
};

function display(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function employeeStatus(value) {
  if (value === 'active') return '在职';
  if (value === 'inactive') return '非在职';
  return display(value);
}

function Top3TieReviewItem({ item, busyId, onConfirm }) {
  const [selectedProjects, setSelectedProjects] = useState(
    item.selected_projects || [],
  );
  const answered = item.decision_status === 'answered';
  const itemBusy = busyId === (item.decision_id || item.tie_ref);
  const selectionComplete = selectedProjects.length === item.slots;
  const inputType = item.slots === 1 ? 'radio' : 'checkbox';

  const toggleProject = (project) => {
    if (inputType === 'radio') {
      setSelectedProjects([project]);
      return;
    }
    setSelectedProjects((current) => (
      current.includes(project)
        ? current.filter((value) => value !== project)
        : current.length < item.slots
          ? [...current, project]
          : current
    ));
  };

  return (
    <article className="weekly-review-item" key={item.tie_ref}>
      <div className="weekly-review-item-heading">
        <div>
          <h3>截止位并列</h3>
          <p>{item.question}</p>
        </div>
        <span className={answered ? 'confirmed' : 'review'}>
          {answered ? '已确认' : `请选择 ${item.slots} 项`}
        </span>
      </div>

      <p className="weekly-decision-context">
        候选项目在第三名截止位人数相同；选择只影响周报前三项目展示，不修改日报或人员事实。
      </p>

      <fieldset className="weekly-project-options" disabled={answered || Boolean(busyId)}>
        <legend>候选项目</legend>
        {item.candidates.map((project) => (
          <label key={project}>
            <input
              type={inputType}
              name={`top3-${item.tie_ref}`}
              checked={selectedProjects.includes(project)}
              onChange={() => toggleProject(project)}
            />
            <span>{project}</span>
          </label>
        ))}
      </fieldset>

      <div className="weekly-review-item-actions">
        {answered ? (
          <span className="weekly-confirmed">
            <CheckCircle2 aria-hidden="true" size={15} />
            已确认 {item.slots} 个项目
          </span>
        ) : (
          <button
            type="button"
            className="weekly-confirm-action"
            disabled={Boolean(busyId) || !selectionComplete}
            onClick={() => onConfirm(item, selectedProjects)}
          >
            {itemBusy
              ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
              : <CheckCircle2 aria-hidden="true" size={15} />}
            确认前三项目
          </button>
        )}
      </div>
    </article>
  );
}

export default function WeeklyReviewPanel({
  items,
  error,
  busyId,
  onConfirm,
  onCreateRevision,
}) {
  if (!items?.length && !error) return null;
  const pendingCount = error
    ? 1
    : items.filter((item) => item.decision_status !== 'answered').length;

  return (
    <section className="weekly-review-panel" aria-labelledby="weekly-review-title">
      <div className="weekly-review-heading">
        <div>
          <h2 id="weekly-review-title">周报复核</h2>
          <p>核对自然人有效记录，以及前三项目并列边界的采用结果。</p>
        </div>
        <span className={pendingCount === 0 ? 'confirmed' : ''}>
          {pendingCount === 0 ? '全部已确认' : `${pendingCount} 项待处理`}
        </span>
      </div>

      {error ? (
        <div className="weekly-review-error" role="alert">
          <CircleAlert aria-hidden="true" size={17} />
          <div>
            <strong>复核证据读取失败</strong>
            <p>{error}</p>
          </div>
          <button
            type="button"
            className="weekly-revision-action"
            disabled={Boolean(busyId)}
            onClick={onCreateRevision}
          >
            {busyId === 'revision'
              ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
              : <RefreshCw aria-hidden="true" size={15} />}
            创建同日修订 Run
          </button>
        </div>
      ) : items.map((item) => {
        if (item.kind === 'top3_cutoff_tie') {
          return (
            <Top3TieReviewItem
              key={`top3-${item.tie_ref}`}
              item={item}
              busyId={busyId}
              onConfirm={onConfirm}
            />
          );
        }
        const selected = item.employments.find((employment) => employment.selected);
        const title = selected?.display_name || selected?.employee_no || '待复核人员';
        const confirmable = item.resolution === 'confirm_dedupe';
        const answered = item.decision_status === 'answered';
        const itemBusy = busyId === (item.decision_id || item.person_ref);
        return (
          <article className="weekly-review-item" key={item.person_ref}>
            <div className="weekly-review-item-heading">
              <div>
                <h3>{title}</h3>
                <p>{item.employments.length} 条有效在职记录</p>
              </div>
              <span className={answered ? 'confirmed' : (confirmable ? 'review' : 'block')}>
                {answered ? '已确认' : (confirmable ? '需确认' : '输入冲突')}
              </span>
            </div>

            {!confirmable && (
              <div className="weekly-conflict-note">
                <CircleAlert aria-hidden="true" size={16} />
                <div>
                  <strong>周报归属维度不一致，当前 Run 不能人工覆盖。</strong>
                  <p>
                    冲突字段：
                    {(item.conflicting_dimensions || []).map((dimension) => (
                      <span key={dimension}>{DIMENSION_LABELS[dimension] || dimension}</span>
                    ))}
                  </p>
                </div>
              </div>
            )}

            <div className="weekly-review-table-scroll">
              <table aria-label={`${title}的周报复核记录`}>
                <thead>
                  <tr>
                    <th>采用状态</th>
                    <th>来源行</th>
                    <th>姓名</th>
                    <th>工号</th>
                    <th>入职日期</th>
                    <th>事业部</th>
                    <th>项目</th>
                    <th>员工类型</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {item.employments.map((employment) => (
                    <tr
                      className={employment.selected ? 'selected' : ''}
                      key={employment.source_row_no}
                    >
                      <td>
                        {employment.selected ? (
                          <span className="weekly-selected-mark">
                            <CheckCircle2 aria-hidden="true" size={14} />系统采用
                          </span>
                        ) : '—'}
                      </td>
                      <td>{employment.source_row_no}</td>
                      <td>{display(employment.display_name)}</td>
                      <td>{display(employment.employee_no)}</td>
                      <td>{display(employment.entry_date)}</td>
                      <td>{display(employment.business_unit_no || employment.business_unit)}</td>
                      <td>{display(employment.project_code || employment.project_name)}</td>
                      <td>{display(employment.employee_type)}</td>
                      <td>{employeeStatus(employment.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="weekly-review-item-actions">
              {confirmable ? (
                answered ? (
                  <span className="weekly-confirmed">
                    <CheckCircle2 aria-hidden="true" size={15} />
                    已确认按自然人计 1 人
                  </span>
                ) : (
                  <button
                    type="button"
                    className="weekly-confirm-action"
                    disabled={Boolean(busyId)}
                    onClick={() => onConfirm(item)}
                  >
                    {itemBusy
                      ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
                      : <CheckCircle2 aria-hidden="true" size={15} />}
                    确认按自然人计 1 人
                  </button>
                )
              ) : (
                <button
                  type="button"
                  className="weekly-revision-action"
                  disabled={Boolean(busyId)}
                  onClick={onCreateRevision}
                >
                  {busyId === 'revision'
                    ? <LoaderCircle className="spin" aria-hidden="true" size={15} />
                    : <RefreshCw aria-hidden="true" size={15} />}
                  创建同日修订 Run
                </button>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
