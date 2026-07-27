import { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, LoaderCircle, RotateCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getCalendarMonth, openCalendarDate } from '../services/calendarService';
import './CalendarPage.css';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

const RUN_STATUS = {
  created: { label: '待上传', tone: 'neutral' },
  parsing: { label: '处理中', tone: 'progress' },
  needs_review: { label: '待确认', tone: 'warning' },
  awaiting_decision: { label: '待确认', tone: 'warning' },
  ready: { label: '待预览', tone: 'ready' },
  failed: { label: '处理失败', tone: 'error' },
};

const REPORT_STATUS = {
  draft: '待处理',
  calculating: '计算中',
  needs_review: '待确认',
  ready: '待发布',
  publishing: '发布中',
  published: '已发布',
  failed: '失败',
  not_due: '未到周报日',
  superseded: '已替代',
  pending: '待处理',
};

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function shiftMonth(month, delta) {
  const [year, monthNumber] = month.split('-').map(Number);
  const shifted = new Date(year, monthNumber - 1 + delta, 1);
  return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, '0')}`;
}

function monthTitle(month) {
  const [year, monthNumber] = month.split('-').map(Number);
  return `${year}年${monthNumber}月`;
}

function dayNumber(date) {
  return Number(date.slice(-2));
}

function firstDayOffset(month) {
  const [year, monthNumber] = month.split('-').map(Number);
  const sundayFirst = new Date(year, monthNumber - 1, 1).getDay();
  return (sundayFirst + 6) % 7;
}

function statusFor(day) {
  if (!day.run_id) return { label: '未开始', tone: 'empty' };
  if (
    day.daily_status === 'published'
    && [null, undefined, 'not_due', 'published'].includes(day.weekly_status)
  ) {
    return { label: '已发布', tone: 'published' };
  }
  return RUN_STATUS[day.run_status] || { label: '进行中', tone: 'progress' };
}

function reportLabel(prefix, value) {
  return value ? `${prefix} ${REPORT_STATUS[value] || value}` : null;
}

function accessibleDayLabel(day) {
  const month = Number(day.date.slice(5, 7));
  const number = dayNumber(day.date);
  const labels = [`${month}月${number}日`, statusFor(day).label];
  const daily = reportLabel('日报', day.daily_status);
  const weekly = reportLabel('周报', day.weekly_status);
  if (daily) labels.push(daily);
  if (weekly) labels.push(weekly);
  if (!day.is_workday) labels.push('非工作日');
  return labels.join('，');
}

export default function CalendarPage({ initialMonth }) {
  const navigate = useNavigate();
  const [month, setMonth] = useState(initialMonth || currentMonth);
  const [days, setDays] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openingDate, setOpeningDate] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');

    getCalendarMonth(month)
      .then((data) => {
        if (active) setDays(Array.isArray(data?.days) ? data.days : []);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '日历加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [month, reloadKey]);

  const calendarCells = useMemo(() => {
    const blanks = Array.from({ length: firstDayOffset(month) }, (_, index) => ({
      key: `blank-${index}`,
      blank: true,
    }));
    return [...blanks, ...days.map((day) => ({ key: day.date, day }))];
  }, [days, month]);

  const openDay = useCallback(async (day) => {
    if ((!day.is_workday && !day.run_id) || openingDate) return;
    if (day.run_id && day.run_status !== 'created') {
      navigate(`/runs/${day.run_id}`);
      return;
    }

    setOpeningDate(day.date);
    setError('');
    try {
      const run = await openCalendarDate(day.date);
      navigate(`/runs/${run.id}`);
    } catch (requestError) {
      setError(requestError.message || '创建运行失败');
    } finally {
      setOpeningDate('');
    }
  }, [navigate, openingDate]);

  return (
    <main className="calendar-page">
      <header className="calendar-header">
        <div>
          <h1>运行日历</h1>
          <p>从报告日期进入当日处理链路，查看日报与周报状态。</p>
        </div>
        <div className="calendar-toolbar" aria-label="月份导航">
          <button
            type="button"
            className="icon-button"
            aria-label="上个月"
            title="上个月"
            onClick={() => setMonth((value) => shiftMonth(value, -1))}
          >
            <ChevronLeft aria-hidden="true" size={18} />
          </button>
          <strong aria-live="polite">{monthTitle(month)}</strong>
          <button
            type="button"
            className="icon-button"
            aria-label="下个月"
            title="下个月"
            onClick={() => setMonth((value) => shiftMonth(value, 1))}
          >
            <ChevronRight aria-hidden="true" size={18} />
          </button>
          <button type="button" className="today-button" onClick={() => setMonth(currentMonth())}>
            今天
          </button>
        </div>
      </header>

      {error && (
        <div className="calendar-alert" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setReloadKey((value) => value + 1)}>
            <RotateCw aria-hidden="true" size={15} />
            重试
          </button>
        </div>
      )}

      <section className="calendar-panel" aria-label={`${monthTitle(month)}报表运行日历`}>
        <div className="calendar-legend" aria-label="状态说明">
          <span><i className="legend-dot ready" />可预览</span>
          <span><i className="legend-dot warning" />待确认</span>
          <span><i className="legend-dot error" />失败</span>
          <span><i className="legend-dot published" />已发布</span>
        </div>

        <div className="calendar-scroll">
          <div className="calendar-grid calendar-weekdays" aria-hidden="true">
            {WEEKDAYS.map((weekday) => <div key={weekday}>周{weekday}</div>)}
          </div>

          {loading ? (
            <div className="calendar-loading" role="status">
              <LoaderCircle className="spin" aria-hidden="true" size={20} />
              正在加载日历
            </div>
          ) : (
            <div className="calendar-grid calendar-days">
              {calendarCells.map((cell) => {
                if (cell.blank) return <div className="calendar-blank" key={cell.key} />;

                const { day } = cell;
                const status = statusFor(day);
                const disabled = !day.is_workday && !day.run_id;
                const isOpening = openingDate === day.date;
                const daily = reportLabel('日报', day.daily_status);
                const weekly = reportLabel('周报', day.weekly_status);

                return (
                  <button
                    type="button"
                    key={cell.key}
                    className={`calendar-day ${day.is_workday ? '' : 'non-workday'}`}
                    aria-label={accessibleDayLabel(day)}
                    disabled={disabled || Boolean(openingDate && !isOpening)}
                    onClick={() => openDay(day)}
                  >
                    <span className="day-topline">
                      <b>{dayNumber(day.date)}</b>
                      <span className={`run-status ${status.tone}`}>{status.label}</span>
                    </span>
                    <span className="report-statuses">
                      {isOpening ? (
                        <span className="opening-run"><LoaderCircle className="spin" size={14} />创建运行</span>
                      ) : (
                        <>
                          {daily && (
                            <span
                              className={`report-badge ${day.daily_status}`}
                              title={daily}
                            >
                              {daily}
                            </span>
                          )}
                          {weekly && (
                            <span
                              className={`report-badge ${day.weekly_status}`}
                              title={weekly}
                            >
                              {weekly}
                            </span>
                          )}
                          {!daily && !weekly && day.is_workday && <span className="no-report">等待录入</span>}
                          {!day.is_workday && <span className="no-report">非工作日</span>}
                        </>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <div className="calendar-guidance">
        <CalendarDays aria-hidden="true" size={18} />
        <p>点击已有日期继续处理；点击空白工作日会创建一条新的运行记录。</p>
      </div>
    </main>
  );
}
