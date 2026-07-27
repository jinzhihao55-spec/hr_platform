import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RunPreviewPage from './RunPreviewPage';
import {
  answerRunDecision,
  createRevisionRun,
  getRun,
  getRunPreview,
  getWeeklyReview,
  publishRun,
} from '../services/runService';
import { getPublishedReport } from '../services/reportService';

vi.mock('../services/runService', () => ({
  answerRunDecision: vi.fn(),
  createRevisionRun: vi.fn(),
  getRun: vi.fn(),
  getRunPreview: vi.fn(),
  getWeeklyReview: vi.fn(),
  publishRun: vi.fn(),
}));

vi.mock('../services/reportService', () => ({
  getPublishedReport: vi.fn(),
}));

const run = {
  id: 'run-preview',
  report_date: '2026-07-15',
  status: 'ready',
  baseline_report_id: 'baseline-14',
  targets: [
    { report_kind: 'daily', status: 'ready' },
    { report_kind: 'weekly', status: 'needs_review' },
  ],
};

const preview = (reportKind, publishable) => ({
  run_id: 'run-preview',
  report_kind: reportKind,
  period_start: reportKind === 'daily' ? '2026-07-15' : '2026-07-13',
  period_end: '2026-07-15',
  rule_version: 'daily-sop-v1',
  snapshot_hash: `${reportKind}-hash`,
  publishable,
  rows: reportKind === 'daily'
    ? { '2': { number: 2, label: '今日入职', value: 2, is_blank: false } }
    : {},
  main_rows: reportKind === 'weekly'
    ? [{ business_unit: 'NENT', headcount: 20, joiners: 2, leavers: 1 }]
    : [],
  cc_rows: [],
  tenure: {},
  validation_summary: {
    publishable,
    pending_decision_count: publishable ? 0 : 1,
    blocking_validation_codes: publishable ? [] : ['weekly_last_workday_only'],
    block_count: 0,
    review_count: publishable ? 0 : 1,
  },
});

function renderPreview() {
  return render(
    <MemoryRouter initialEntries={['/runs/run-preview/preview']}>
      <Routes>
        <Route path="/runs/:runId/preview" element={<RunPreviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const confirmableWeeklyReview = {
  items: [{
    person_ref: 'abc123def456',
    severity: 'REVIEW',
    resolution: 'confirm_dedupe',
    decision_id: 'weekly-decision-1',
    decision_status: 'pending',
    conflicting_dimensions: [],
    selected_source_row_no: 8,
    employments: [
      {
        source_row_no: 7,
        employee_no: 'FAKE-E1',
        display_name: '测试甲',
        entry_date: '2025-01-01',
        business_unit: '网络事业部',
        project_name: '测试项目',
        employee_type: '正式员工',
        status: 'active',
        selected: false,
      },
      {
        source_row_no: 8,
        employee_no: 'FAKE-E2',
        display_name: '测试甲',
        entry_date: '2026-07-08',
        business_unit: '网络事业部',
        project_name: '测试项目',
        employee_type: '正式员工',
        status: 'active',
        selected: true,
      },
    ],
  }],
};

const top3TieWeeklyReview = {
  items: [{
    kind: 'top3_cutoff_tie',
    tie_ref: 'tie123abc456',
    severity: 'REVIEW',
    resolution: 'select_top3_projects',
    decision_id: 'weekly-top3-decision-1',
    decision_status: 'pending',
    question: '测试事业部的前三项目在截止位并列，请选择 1 个项目。',
    candidates: ['测试项目甲', '测试项目乙'],
    slots: 1,
    selected_projects: [],
  }],
};

describe('RunPreviewPage', () => {
  beforeEach(() => {
    answerRunDecision.mockReset();
    createRevisionRun.mockReset();
    getRun.mockReset();
    getRunPreview.mockReset();
    getWeeklyReview.mockReset();
    publishRun.mockReset();
    getPublishedReport.mockReset();
    getRun.mockResolvedValue(run);
    getRunPreview.mockImplementation((_runId, reportKind) => (
      Promise.resolve(preview(reportKind, reportKind === 'daily'))
    ));
    getWeeklyReview.mockResolvedValue({ items: [] });
    getPublishedReport.mockResolvedValue({
      id: 'baseline-14',
      snapshot: { rows: { '2': { label: '今日入职', value: 1, is_blank: false } } },
    });
  });

  it('allows daily publication while weekly remains in review', async () => {
    renderPreview();

    expect(await screen.findByRole('button', { name: '发布日报' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '发布周报' })).toBeDisabled();
  });

  it('serializes stateful daily and weekly preview calculations', async () => {
    let resolveDaily;
    getRunPreview.mockImplementation((_runId, reportKind) => {
      if (reportKind === 'daily') {
        return new Promise((resolve) => {
          resolveDaily = resolve;
        });
      }
      return Promise.resolve(preview('weekly', false));
    });
    renderPreview();

    await waitFor(() => {
      expect(getRunPreview).toHaveBeenCalledWith('run-preview', 'daily');
    });
    expect(getRunPreview).not.toHaveBeenCalledWith('run-preview', 'weekly');

    resolveDaily(preview('daily', true));

    await waitFor(() => {
      expect(getRunPreview).toHaveBeenCalledWith('run-preview', 'weekly');
    });
  });

  it('publishes only the selected report target', async () => {
    publishRun.mockResolvedValue({ reports: [{ id: 'daily-report-1', report_kind: 'daily' }] });
    const user = userEvent.setup();
    renderPreview();

    await user.click(await screen.findByRole('button', { name: '发布日报' }));

    expect(publishRun).toHaveBeenCalledWith('run-preview', ['daily']);
  });

  it('refreshes the weekly preview after daily publication', async () => {
    let weeklyRequests = 0;
    getRunPreview.mockImplementation((_runId, reportKind) => {
      if (reportKind === 'daily') return Promise.resolve(preview('daily', true));
      weeklyRequests += 1;
      return Promise.resolve(preview('weekly', weeklyRequests > 1));
    });
    publishRun.mockResolvedValue({
      reports: [{ id: 'daily-report-1', report_kind: 'daily' }],
    });
    const user = userEvent.setup();
    renderPreview();

    const weeklyButton = await screen.findByRole('button', { name: '发布周报' });
    expect(weeklyButton).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '发布日报' }));

    expect(await screen.findByRole('button', { name: '发布周报' })).toBeEnabled();
    expect(weeklyRequests).toBe(2);
  });

  it('explains why a partial-week preview cannot be published', async () => {
    const user = userEvent.setup();
    renderPreview();

    expect(await screen.findByText('未到周报日')).toBeVisible();

    await user.click(await screen.findByRole('button', { name: '周报预览' }));

    expect(screen.getByText('过程预览')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent(
      '周报仅在本周最后一个工作日发布',
    );
  });

  it('opens Friday weekly review, confirms dedupe, and unlocks weekly publish', async () => {
    getRun.mockResolvedValue({ ...run, report_date: '2026-07-17' });
    let weeklyPreviewRequests = 0;
    getRunPreview.mockImplementation((_runId, reportKind) => {
      if (reportKind === 'daily') return Promise.resolve(preview('daily', true));
      weeklyPreviewRequests += 1;
      const result = preview('weekly', weeklyPreviewRequests > 1);
      result.period_end = '2026-07-17';
      result.validation_summary.blocking_validation_codes = result.publishable
        ? []
        : ['multiple_active_employments'];
      return Promise.resolve(result);
    });
    getWeeklyReview
      .mockResolvedValueOnce(confirmableWeeklyReview)
      .mockResolvedValue({
        items: [{
          ...confirmableWeeklyReview.items[0],
          decision_status: 'answered',
        }],
      });
    answerRunDecision.mockResolvedValue({
      id: 'weekly-decision-1',
      status: 'answered',
      answer: '确认按自然人计1人',
    });
    const user = userEvent.setup();
    renderPreview();

    expect(await screen.findByRole('heading', { name: '周报复核' })).toBeVisible();
    expect(screen.getByText('FAKE-E2')).toBeVisible();
    expect(screen.getByText('系统采用')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '确认按自然人计 1 人' }));

    expect(answerRunDecision).toHaveBeenCalledWith(
      'run-preview',
      'weekly-decision-1',
      '确认按自然人计1人',
    );
    expect(await screen.findByRole('button', { name: '发布周报' })).toBeEnabled();
    expect(screen.getByText('全部已确认')).toBeVisible();
    expect(screen.queryByText('1 项待处理')).not.toBeInTheDocument();
    expect(screen.queryByText('需确认')).not.toBeInTheDocument();
  });

  it('requires a cutoff-tie project selection before weekly publication', async () => {
    getRun.mockResolvedValue({ ...run, report_date: '2026-07-17' });
    let weeklyPreviewRequests = 0;
    getRunPreview.mockImplementation((_runId, reportKind) => {
      if (reportKind === 'daily') return Promise.resolve(preview('daily', true));
      weeklyPreviewRequests += 1;
      const result = preview('weekly', weeklyPreviewRequests > 1);
      result.period_end = '2026-07-17';
      result.validation_summary.blocking_validation_codes = result.publishable
        ? []
        : ['top3_cutoff_tie'];
      return Promise.resolve(result);
    });
    getWeeklyReview
      .mockResolvedValueOnce(top3TieWeeklyReview)
      .mockResolvedValue({
        items: [{
          ...top3TieWeeklyReview.items[0],
          decision_status: 'answered',
          selected_projects: ['测试项目乙'],
        }],
      });
    answerRunDecision.mockResolvedValue({
      id: 'weekly-top3-decision-1',
      status: 'answered',
      answer: ['测试项目乙'],
    });
    const user = userEvent.setup();
    renderPreview();

    expect(await screen.findByRole('heading', { name: '周报复核' })).toBeVisible();
    expect(screen.getByText('截止位并列')).toBeVisible();
    expect(screen.getByText(/选择只影响周报前三项目展示/)).toBeVisible();
    expect(screen.getByRole('button', { name: '发布周报' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: '测试项目乙' }));
    await user.click(screen.getByRole('button', { name: '确认前三项目' }));

    expect(answerRunDecision).toHaveBeenCalledWith(
      'run-preview',
      'weekly-top3-decision-1',
      ['测试项目乙'],
    );
    expect(await screen.findByRole('button', { name: '发布周报' })).toBeEnabled();
    expect(screen.getByText('已确认 1 个项目')).toBeVisible();
  });

  it('offers only a same-day revision for conflicting employment dimensions', async () => {
    getRun.mockResolvedValue({ ...run, report_date: '2026-07-17' });
    getRunPreview.mockImplementation((_runId, reportKind) => {
      const result = preview(reportKind, reportKind === 'daily');
      if (reportKind === 'weekly') {
        result.period_end = '2026-07-17';
        result.validation_summary.block_count = 1;
        result.validation_summary.review_count = 0;
        result.validation_summary.blocking_validation_codes = [
          'multiple_active_employments',
        ];
      }
      return Promise.resolve(result);
    });
    getWeeklyReview.mockResolvedValue({
      items: [{
        ...confirmableWeeklyReview.items[0],
        severity: 'BLOCK',
        resolution: 'replace_input',
        decision_id: null,
        decision_status: null,
        conflicting_dimensions: ['project_name'],
      }],
    });
    createRevisionRun.mockResolvedValue({ run: { id: 'revision-run-1' } });
    const user = userEvent.setup();
    renderPreview();

    expect(await screen.findByRole('heading', { name: '周报复核' })).toBeVisible();
    expect(screen.getByText('项目名称')).toBeVisible();
    expect(
      screen.queryByRole('button', { name: '确认按自然人计 1 人' }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '创建同日修订 Run' }));

    expect(createRevisionRun).toHaveBeenCalledWith('2026-07-17');
  });

  it('keeps a superseded target read-only and offers a same-day revision', async () => {
    getRun.mockResolvedValue({
      ...run,
      report_date: '2026-07-17',
      targets: [
        { report_kind: 'daily', status: 'published' },
        { report_kind: 'weekly', status: 'superseded' },
      ],
    });
    getRunPreview.mockImplementation((_runId, reportKind) => (
      Promise.resolve(preview(reportKind, true))
    ));
    createRevisionRun.mockResolvedValue({ run: { id: 'revision-run-1' } });
    const user = userEvent.setup();
    renderPreview();

    expect(await screen.findByRole('button', { name: '周报已替代' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '发布周报' })).not.toBeInTheDocument();
    expect(screen.getByText('该 Run 的周报已被同日后续版本替代。')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '创建同日修订 Run' }));

    expect(createRevisionRun).toHaveBeenCalledWith('2026-07-17');
  });
});
