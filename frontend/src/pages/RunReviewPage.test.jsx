import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RunReviewPage from './RunReviewPage';
import { answerRunDecision, getDecisionPreview } from '../services/runService';

vi.mock('../services/runService', () => ({
  answerRunDecision: vi.fn(),
  getDecisionPreview: vi.fn(),
}));

const reviewRun = {
  id: 'run-review',
  status: 'needs_review',
  baseline_report_id: 'baseline-1',
  decisions: [
    {
      id: 'decision-1',
      decision_code: 'ocr_review_required',
      fact_ref: 'source:release:row:ocr',
      question: '请确认 OA/Release 图片识别结果。',
      options: ['确认', '替换输入'],
      answer: null,
      status: 'pending',
    },
  ],
};

describe('RunReviewPage', () => {
  beforeEach(() => {
    answerRunDecision.mockReset();
    getDecisionPreview.mockReset();
    getDecisionPreview.mockResolvedValue({
      kind: 'ocr_source',
      source_type: 'release',
      columns: [
        { key: 'source_row_no', label: '来源行' },
        { key: 'order_no', label: '单号' },
        { key: 'process_status', label: '流程状态' },
      ],
      rows: [
        { source_row_no: 2, order_no: 'FAKE-REL-001', process_status: '审批中' },
      ],
      warnings: ['原始图片按安全策略不留存；请核对结构化结果。'],
    });
  });

  it('shows structured OCR evidence before a pending confirmation', async () => {
    render(<RunReviewPage run={reviewRun} onRefresh={vi.fn()} onContinue={vi.fn()} />);

    expect(
      await screen.findByRole('table', { name: 'OA/Release 识别结果' }),
    ).toBeVisible();
    expect(screen.getByText('FAKE-REL-001')).toBeVisible();
    expect(screen.getByText(/原始图片按安全策略不留存/)).toBeVisible();
    expect(getDecisionPreview).toHaveBeenCalledWith('run-review', 'decision-1');
  });

  it('keeps OCR evidence available after confirmation', async () => {
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          status: 'ready',
          decisions: [{
            ...reviewRun.decisions[0],
            status: 'answered',
            answer: '确认',
          }],
        }}
        onRefresh={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(await screen.findByText('查看识别结果')).toBeVisible();
    expect(getDecisionPreview).toHaveBeenCalledWith('run-review', 'decision-1');
  });

  it('keeps preview disabled until review decisions are resolved', () => {
    render(<RunReviewPage run={reviewRun} onRefresh={vi.fn()} onContinue={vi.fn()} />);

    expect(screen.getByRole('button', { name: /无法预览：还有 1 项需要确认/ })).toBeDisabled();
  });

  it('answers a decision and refreshes the complete run view', async () => {
    answerRunDecision.mockResolvedValue({ status: 'answered', answer: '确认' });
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RunReviewPage run={reviewRun} onRefresh={onRefresh} onContinue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: '确认' }));

    expect(answerRunDecision).toHaveBeenCalledWith('run-review', 'decision-1', '确认');
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('submits recruitment forecast corrections as two non-negative integers', async () => {
    answerRunDecision.mockResolvedValue({ status: 'answered' });
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          decisions: [{
            id: 'decision-recruitment',
            decision_code: 'recruitment_label_uncertain',
            fact_ref: 'source:recruitment:row:4',
            question: '招聘动态月份列未完整识别，请确认本月两列数值。',
            options: ['补充数值', '替换输入'],
            answer: null,
            status: 'pending',
          }],
        }}
        onRefresh={onRefresh}
        onContinue={vi.fn()}
      />,
    );

    const previous = screen.getByRole('spinbutton', {
      name: '上月 Offer 当月预计入职',
    });
    const current = screen.getByRole('spinbutton', {
      name: '当月 Offer 当月预计入职',
    });
    const submit = screen.getByRole('button', { name: '补充数值' });
    expect(submit).toBeDisabled();

    await user.type(previous, '2');
    await user.type(current, '3');
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(answerRunDecision).toHaveBeenCalledWith(
      'run-review',
      'decision-recruitment',
      {
        previous_month_offer_current_month_onboard: 2,
        current_month_offer_current_month_onboard: 3,
      },
    );
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('requires a last working day for an OCR release row', async () => {
    answerRunDecision.mockResolvedValue({ status: 'answered' });
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          decisions: [{
            id: 'decision-release-lwd',
            decision_code: 'release_lwd_missing',
            fact_ref: 'source:release:row:2',
            question: 'OA/Release 来源行 2 缺少最后工作日（LWD），请补充。',
            options: ['补充最后工作日', '替换输入'],
            answer: null,
            status: 'pending',
          }],
        }}
        onRefresh={onRefresh}
        onContinue={vi.fn()}
      />,
    );

    const dateInput = screen.getByLabelText('最后工作日（LWD）');
    const submit = screen.getByRole('button', { name: '确认最后工作日' });
    expect(submit).toBeDisabled();

    await user.type(dateInput, '2026-08-14');
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(answerRunDecision).toHaveBeenCalledWith(
      'run-review',
      'decision-release-lwd',
      { last_working_day: '2026-08-14' },
    );
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('refreshes OCR evidence after a related LWD decision changes', async () => {
    const preview = (lastWorkingDay) => ({
      kind: 'ocr_source',
      source_type: 'release',
      columns: [{ key: 'last_working_day', label: '最后工作日' }],
      rows: [{ source_row_no: 2, last_working_day: lastWorkingDay }],
      warnings: [],
    });
    getDecisionPreview
      .mockResolvedValueOnce(preview(null))
      .mockResolvedValueOnce(preview('2026-08-14'));
    const lwdDecision = {
      id: 'decision-release-lwd',
      decision_code: 'release_lwd_missing',
      fact_ref: 'source:release:row:2',
      question: '请补充最后工作日。',
      options: ['补充最后工作日', '替换输入'],
      answer: null,
      status: 'pending',
    };
    const props = { onRefresh: vi.fn(), onContinue: vi.fn() };
    const { rerender } = render(
      <RunReviewPage
        {...props}
        run={{ ...reviewRun, decisions: [reviewRun.decisions[0], lwdDecision] }}
      />,
    );
    const table = await screen.findByRole('table', { name: 'OA/Release 识别结果' });
    expect(within(table).getByText('—')).toBeVisible();

    rerender(
      <RunReviewPage
        {...props}
        run={{
          ...reviewRun,
          decisions: [
            reviewRun.decisions[0],
            {
              ...lwdDecision,
              status: 'answered',
              answer: { last_working_day: '2026-08-14' },
            },
          ],
        }}
      />,
    );

    await waitFor(() => expect(getDecisionPreview).toHaveBeenCalledTimes(2));
    expect(within(table).getByText('2026-08-14')).toBeVisible();
  });

  it('opens the matching source picker instead of submitting replacement as an answer', async () => {
    const onReplaceInput = vi.fn();
    const user = userEvent.setup();
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          decisions: [{
            id: 'decision-recruitment',
            decision_code: 'recruitment_label_uncertain',
            fact_ref: 'source:recruitment:row:4',
            question: '招聘动态月份列未完整识别，请确认本月两列数值。',
            options: ['补充数值', '替换输入'],
            answer: null,
            status: 'pending',
          }],
        }}
        onRefresh={vi.fn()}
        onContinue={vi.fn()}
        onReplaceInput={onReplaceInput}
      />,
    );

    await user.click(screen.getByRole('button', { name: '替换输入' }));

    expect(onReplaceInput).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'decision-recruitment' }),
    );
    expect(answerRunDecision).not.toHaveBeenCalled();
  });

  it('shows a durable status while the final confirmation is processed', async () => {
    let resolveAnswer;
    answerRunDecision.mockReturnValue(new Promise((resolve) => {
      resolveAnswer = resolve;
    }));
    const user = userEvent.setup();
    render(<RunReviewPage run={reviewRun} onRefresh={vi.fn()} onContinue={vi.fn()} />);

    const click = user.click(screen.getByRole('button', { name: '确认' }));

    expect(
      await screen.findByText(/正在确认并冻结本次输入/),
    ).toBeVisible();
    expect(screen.getByRole('button', { name: '确认' })).toBeDisabled();

    resolveAnswer({ status: 'answered', answer: '确认' });
    await click;
  });

  it('explains that a published first run is the initial baseline', () => {
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          status: 'ready',
          baseline_report_id: null,
          decisions: [],
          targets: [{ report_kind: 'daily', status: 'published' }],
        }}
        onRefresh={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(screen.getByText('本日已作为初始基线发布')).toBeVisible();
    expect(screen.queryByText('缺少上一份已发布日报基线')).not.toBeInTheDocument();
  });

  it('prioritizes pending confirmation over the missing initial baseline', () => {
    render(
      <RunReviewPage
        run={{ ...reviewRun, baseline_report_id: null }}
        onRefresh={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(screen.getByText('还有 1 项需要确认')).toBeVisible();
  });

  it('does not treat the midweek weekly publish rule as a daily blocker', () => {
    render(
      <RunReviewPage
        run={{
          ...reviewRun,
          status: 'ready',
          decisions: [],
          validations: [{
            report_kind: 'weekly',
            validation_code: 'weekly_last_workday_only',
            severity: 'BLOCK',
            outcome: 'FAIL',
          }],
          targets: [
            { report_kind: 'daily', status: 'published' },
            { report_kind: 'weekly', status: 'failed' },
          ],
        }}
        onRefresh={vi.fn()}
        onContinue={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '预览日报与周报' })).toBeEnabled();
    expect(screen.queryByText('仍有阻断校验未通过')).not.toBeInTheDocument();
  });
});
