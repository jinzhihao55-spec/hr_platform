import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from './apiClient';
import {
  createRevisionRun,
  getDecisionPreview,
  getRun,
  getRunPreview,
  getWeeklyReview,
  publishRun,
  uploadRunSource,
} from './runService';

vi.mock('./apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('runService', () => {
  beforeEach(() => {
    apiClient.get.mockReset();
    apiClient.post.mockReset();
    apiClient.put.mockReset();
  });

  it('allows remote OCR uploads to run longer than the global request timeout', () => {
    const file = new File(['image'], '招聘截图.png', { type: 'image/png' });

    uploadRunSource('run-1', 'recruitment', file);

    expect(apiClient.put).toHaveBeenCalledWith(
      '/runs/run-1/sources/recruitment',
      expect.any(FormData),
      expect.objectContaining({ timeout: 450000 }),
    );
  });

  it('keeps deterministic Excel uploads on the shorter timeout', () => {
    const file = new File(['table'], '人员表.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });

    uploadRunSource('run-1', 'personnel', file);

    expect(apiClient.put).toHaveBeenCalledWith(
      '/runs/run-1/sources/personnel',
      expect.any(FormData),
      expect.objectContaining({ timeout: 180000 }),
    );
  });

  it('loads structured evidence for one review decision', () => {
    getDecisionPreview('run-1', 'decision-1');

    expect(apiClient.get).toHaveBeenCalledWith(
      '/runs/run-1/decisions/decision-1/preview',
    );
  });

  it('loads weekly review evidence for a Run', () => {
    getWeeklyReview('run-1');

    expect(apiClient.get).toHaveBeenCalledWith('/runs/run-1/weekly/review');
  });

  it('allows the preview workflow to wait through a transient proxy stall', () => {
    getRun('run-1');

    expect(apiClient.get).toHaveBeenCalledWith(
      '/runs/run-1',
      { timeout: 180000 },
    );
  });

  it('allows report preview to use the reverse proxy long-operation timeout', () => {
    getRunPreview('run-1', 'weekly');

    expect(apiClient.get).toHaveBeenCalledWith(
      '/runs/run-1/preview/weekly',
      { timeout: 180000 },
    );
  });

  it('allows report publication to use the reverse proxy long-operation timeout', () => {
    publishRun('run-1', ['weekly']);

    expect(apiClient.post).toHaveBeenCalledWith(
      '/runs/run-1/publish',
      {
        report_kinds: ['weekly'],
        operator_ref: 'local-operator',
      },
      { timeout: 180000 },
    );
  });

  it('creates an empty same-day revision Run', () => {
    createRevisionRun('2026-07-17');

    expect(apiClient.post).toHaveBeenCalledWith('/runs', {
      report_date: '2026-07-17',
      create_new: true,
    });
  });
});
