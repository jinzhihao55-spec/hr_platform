import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RunWorkspacePage from './RunWorkspacePage';
import {
  answerRunDecision,
  createRevisionRun,
  finalizeRunBaseline,
  getRun,
  retryRun,
  uploadRunSource,
} from '../services/runService';

vi.mock('../services/runService', () => ({
  createRevisionRun: vi.fn(),
  getRun: vi.fn(),
  uploadRunSource: vi.fn(),
  answerRunDecision: vi.fn(),
  finalizeRunBaseline: vi.fn(),
  retryRun: vi.fn(),
}));

const emptyRun = {
  id: 'run-1',
  report_date: '2026-07-15',
  status: 'created',
  rule_version: 'daily-sop-v1',
  baseline_report_id: 'baseline-1',
  source_bundle_hash: null,
  sources: [],
  decisions: [],
  validations: [],
  targets: [
    { report_kind: 'daily', status: 'draft' },
    { report_kind: 'weekly', status: 'draft' },
  ],
};

function renderWorkspace() {
  return render(
    <MemoryRouter initialEntries={['/runs/run-1']}>
      <Routes>
        <Route path="/runs/:runId" element={<RunWorkspacePage />} />
        <Route path="/runs/:runId/preview" element={<div>预览页面</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RunWorkspacePage', () => {
  beforeEach(() => {
    answerRunDecision.mockReset();
    getRun.mockReset();
    createRevisionRun.mockReset();
    uploadRunSource.mockReset();
    finalizeRunBaseline.mockReset();
    retryRun.mockReset();
    getRun.mockResolvedValue(emptyRun);
  });

  it('never assigns a rejected file to another empty source slot', async () => {
    uploadRunSource.mockRejectedValue(new Error('文件结构与人员表不匹配'));
    const user = userEvent.setup();
    renderWorkspace();

    const personnelInput = await screen.findByLabelText('人员表');
    const resignationInput = screen.getByLabelText('离职人员报表');
    const wrongSchemaFile = new File(['not-a-personnel-table'], '未知数据.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });

    await user.upload(personnelInput, wrongSchemaFile);

    expect(await screen.findByText('文件结构与人员表不匹配')).toBeVisible();
    expect(uploadRunSource).toHaveBeenCalledWith('run-1', 'personnel', wrongSchemaFile);
    expect(resignationInput).toHaveValue('');
  });

  it('shows the four formal source slots without a resignation-detail input', async () => {
    renderWorkspace();

    expect(await screen.findByLabelText('人员表')).toBeInTheDocument();
    expect(screen.getByLabelText('离职人员报表')).toBeInTheDocument();
    expect(screen.getByLabelText('协议签署 / OA Release')).toBeInTheDocument();
    expect(screen.getByLabelText('招聘数据')).toBeInTheDocument();
    expect(screen.queryByLabelText('离职明细')).not.toBeInTheDocument();
  });

  it('retries a failed run before allowing more input changes', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'failed',
      error_code: 'publication_failed',
      error_message: 'Excel 校验失败',
    });
    retryRun.mockResolvedValue({ ...emptyRun, status: 'parsing' });
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(await screen.findByRole('button', { name: '重试运行' }));

    expect(retryRun).toHaveBeenCalledWith('run-1');
    expect(getRun).toHaveBeenCalledTimes(2);
  });

  it('finalizes the first four-source run with its same-day approved workbook', async () => {
    const stagedRun = {
      ...emptyRun,
      status: 'needs_review',
      baseline_report_id: null,
      sources: [
        { source_type: 'personnel' },
        { source_type: 'resignation' },
        { source_type: 'release' },
        { source_type: 'recruitment' },
      ],
    };
    getRun
      .mockResolvedValueOnce(stagedRun)
      .mockResolvedValueOnce({
        ...stagedRun,
        status: 'ready',
        source_bundle_hash: 'f'.repeat(64),
        targets: [
          { report_kind: 'daily', status: 'published' },
          { report_kind: 'weekly', status: 'draft' },
        ],
      });
    finalizeRunBaseline.mockResolvedValue({ baseline_report_id: 'baseline-1' });
    const user = userEvent.setup();
    renderWorkspace();

    const file = new File(['approved'], '已验收日报.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(
      await screen.findByLabelText('上传本日已验收日报并建立初始基线'),
      file,
    );

    expect(finalizeRunBaseline).toHaveBeenCalledWith('run-1', file);
    expect(await screen.findByText('初始基线已建立，可从日历创建下一工作日运行')).toBeVisible();
  });

  it('does not enable initial baseline upload before all four sources are ready', async () => {
    getRun.mockResolvedValue({ ...emptyRun, baseline_report_id: null });
    renderWorkspace();

    expect(
      await screen.findByLabelText('上传本日已验收日报并建立初始基线'),
    ).toBeDisabled();
    expect(screen.getByText('先完成四项输入和全部人工确认')).toBeVisible();
  });

  it('shows a fully published run as complete instead of still previewable', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'ready',
      source_bundle_hash: 'f'.repeat(64),
      targets: [
        { report_kind: 'daily', status: 'published' },
        { report_kind: 'weekly', status: 'published' },
      ],
    });
    renderWorkspace();

    expect(await screen.findByText('日报/周报已发布')).toBeVisible();
    const completedPublication = screen.getByText('完成发布').closest('li');
    expect(completedPublication).toHaveClass('complete');
    expect(completedPublication).not.toHaveAttribute('aria-current');
    expect(screen.queryByText('可预览')).not.toBeInTheDocument();
  });

  it('blocks preview when the API returns an uppercase blocking validation failure', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'ready',
      validations: [
        { severity: 'BLOCK', outcome: 'FAIL', validation_code: 'row_check' },
      ],
    });
    renderWorkspace();

    expect(await screen.findByText('仍有阻断校验未通过')).toBeVisible();
    expect(screen.getByRole('button', { name: /无法预览：仍有阻断校验未通过/ })).toBeDisabled();
  });

  it('routes weekly decisions to report preview without blocking daily preview', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'ready',
      source_bundle_hash: 'f'.repeat(64),
      sources: [
        { source_type: 'personnel' },
        { source_type: 'resignation' },
        { source_type: 'release' },
        { source_type: 'recruitment' },
      ],
      decisions: [{
        id: 'weekly-top3-1',
        report_kind: 'weekly',
        decision_code: 'top3_cutoff_tie',
        fact_ref: 'weekly:top3_cutoff_tie:fake123abc45:1',
        question: '前三项目在截止位并列，请选择 1 个项目。',
        options: ['候选项目甲', '候选项目乙'],
        status: 'pending',
      }],
      validations: [{
        report_kind: 'weekly',
        severity: 'REVIEW',
        outcome: 'FAIL',
        validation_code: 'top3_cutoff_tie',
      }],
      targets: [
        { report_kind: 'daily', status: 'ready' },
        { report_kind: 'weekly', status: 'needs_review' },
      ],
    });
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByText('周报还有 1 项待复核')).toBeVisible();
    expect(screen.queryByRole('button', { name: '候选项目甲' })).not.toBeInTheDocument();
    const previewButton = screen.getByRole('button', { name: /预览日报与周报/ });
    expect(previewButton).toBeEnabled();

    await user.click(previewButton);

    expect(await screen.findByText('预览页面')).toBeVisible();
  });

  it('creates a same-day revision when frozen input must be replaced', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'ready',
      source_bundle_hash: 'f'.repeat(64),
    });
    createRevisionRun.mockResolvedValue({ run: { id: 'revision-run-1' } });
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(await screen.findByRole('button', { name: '创建同日修订 Run' }));

    expect(createRevisionRun).toHaveBeenCalledWith('2026-07-15');
  });

  it('opens the recruitment file picker from a replacement decision', async () => {
    getRun.mockResolvedValue({
      ...emptyRun,
      status: 'needs_review',
      sources: [{
        source_type: 'recruitment',
        row_count: 8,
        parse_status: 'needs_review',
        original_extension: '.png',
      }],
      decisions: [{
        id: 'decision-recruitment',
        decision_code: 'recruitment_label_uncertain',
        fact_ref: 'source:recruitment:row:4',
        question: '招聘动态月份列未完整识别，请确认本月两列数值。',
        options: ['补充数值', '替换输入'],
        answer: null,
        status: 'pending',
      }],
    });
    const user = userEvent.setup();
    renderWorkspace();

    const recruitmentInput = await screen.findByLabelText('招聘数据');
    const pickerSpy = vi.spyOn(recruitmentInput, 'click');
    await user.click(screen.getByRole('button', { name: '替换输入' }));

    expect(pickerSpy).toHaveBeenCalledOnce();
    expect(answerRunDecision).not.toHaveBeenCalled();
  });

  it('keeps a durable status visible while Qwen processes an image upload', async () => {
    uploadRunSource.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderWorkspace();

    const image = new File(['image'], '协议签署.png', { type: 'image/png' });
    await user.upload(await screen.findByLabelText('协议签署 / OA Release'), image);

    expect(
      await screen.findByText(/图片识别处理中，可能需要 2-7 分钟/),
    ).toBeVisible();
  });
});
