import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Archive from './Archive';
import { downloadPublishedArtifact, getPublishedReports } from '../services';

vi.mock('../services', () => ({
  downloadPublishedArtifact: vi.fn(),
  getPublishedReports: vi.fn(),
}));

describe('Archive', () => {
  beforeEach(() => {
    getPublishedReports.mockReset();
    downloadPublishedArtifact.mockReset();
  });

  it('downloads history artifacts by report id rather than file path', async () => {
    getPublishedReports.mockImplementation((kind) => Promise.resolve(kind === 'daily' ? [
      {
        id: 'daily-history-1', run_id: 'run-1', report_kind: 'daily',
        period_start: '2026-07-15', period_end: '2026-07-15', version: 1,
        is_current: true, published_at: '2026-07-15T18:00:00',
      },
    ] : []));
    downloadPublishedArtifact.mockResolvedValue(new Blob(['daily']));
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const user = userEvent.setup();
    render(<MemoryRouter><Archive /></MemoryRouter>);

    const downloadButton = await screen.findByRole('button', { name: '下载日报 Excel' });
    await user.click(downloadButton);

    await waitFor(() => {
      expect(downloadPublishedArtifact).toHaveBeenCalledWith('daily-history-1', 'excel');
    });
    clickSpy.mockRestore();
  });
});
