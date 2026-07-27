import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DailyReport from './DailyReport';
import WeeklyReport from './WeeklyReport';
import {
  downloadPublishedArtifact,
  getPublishedReport,
  getPublishedReports,
} from '../services';

vi.mock('../services', () => ({
  downloadPublishedArtifact: vi.fn(),
  getPublishedReport: vi.fn(),
  getPublishedReports: vi.fn(),
}));

const reportList = [
  { id: 'report-7', report_kind: 'daily', period_start: '2026-07-07', period_end: '2026-07-07', version: 1, is_current: true },
  { id: 'report-8', report_kind: 'daily', period_start: '2026-07-08', period_end: '2026-07-08', version: 1, is_current: true },
  { id: 'report-9', report_kind: 'daily', period_start: '2026-07-09', period_end: '2026-07-09', version: 1, is_current: true },
];

function detailFor(id, date, value) {
  return {
    id,
    report_kind: 'daily',
    period_start: date,
    period_end: date,
    version: 1,
    snapshot: {
      rows: {
        '2': { label: '今日入职', value, is_blank: false },
        '3': { label: '今日离职', value: 0, is_blank: false },
      },
      tenure: { rows: [] },
      validation_summary: { publishable: true, block_count: 0, review_count: 0 },
    },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

describe('published report period switching', () => {
  beforeEach(() => {
    getPublishedReports.mockReset();
    getPublishedReport.mockReset();
    downloadPublishedArtifact.mockReset();
  });

  it('does not expose stale report data while a new date is loading', async () => {
    const report8 = deferred();
    const report9 = deferred();
    getPublishedReports.mockResolvedValue(reportList);
    getPublishedReport.mockImplementation((reportId) => {
      if (reportId === 'report-7') return Promise.resolve(detailFor('report-7', '2026-07-07', 7));
      if (reportId === 'report-8') return report8.promise;
      return report9.promise;
    });
    const user = userEvent.setup();
    render(<DailyReport />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '下载日报' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /2026-07-08/ }));
    await user.click(screen.getByRole('button', { name: /2026-07-09/ }));

    expect(screen.getByRole('button', { name: '下载日报' })).toBeDisabled();

    await act(async () => {
      report9.resolve(detailFor('report-9', '2026-07-09', 9));
    });
    expect(await screen.findByText(/报告日期 2026-07-09/)).toBeVisible();
    expect(screen.getByRole('button', { name: '下载日报' })).toBeEnabled();

    await act(async () => {
      report8.resolve(detailFor('report-8', '2026-07-08', 8));
    });
    expect(screen.getByText(/报告日期 2026-07-09/)).toBeVisible();
  });

  it('downloads a weekly artifact by immutable report id', async () => {
    getPublishedReports.mockResolvedValue([
      {
        id: 'weekly-report-1',
        report_kind: 'weekly',
        period_start: '2026-07-06',
        period_end: '2026-07-10',
        version: 1,
        is_current: true,
      },
    ]);
    getPublishedReport.mockResolvedValue({
      id: 'weekly-report-1',
      report_kind: 'weekly',
      period_start: '2026-07-06',
      period_end: '2026-07-10',
      version: 1,
      snapshot: { main_rows: [], cc_rows: [], validation_summary: { publishable: true } },
    });
    downloadPublishedArtifact.mockResolvedValue(new Blob(['weekly']));
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<WeeklyReport />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '下载周报' })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: '下载周报' }));

    expect(downloadPublishedArtifact).toHaveBeenCalledWith('weekly-report-1', 'excel');
    clickSpy.mockRestore();
  });
});
