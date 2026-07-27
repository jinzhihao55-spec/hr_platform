import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from './apiClient';
import { getCalendarMonth } from './calendarService';
import { getPublishedReports } from './reportService';
import { getRun } from './runService';

vi.mock('./apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('gateway API paths', () => {
  beforeEach(() => {
    apiClient.get.mockReset();
  });

  it('lets the shared client add the only public /api prefix', () => {
    getCalendarMonth('2026-07');
    getRun('run-1');
    getPublishedReports('daily');

    expect(apiClient.get).toHaveBeenNthCalledWith(
      1,
      '/calendar',
      { params: { month: '2026-07' } },
    );
    expect(apiClient.get).toHaveBeenNthCalledWith(
      2,
      '/runs/run-1',
      { timeout: 180000 },
    );
    expect(apiClient.get).toHaveBeenNthCalledWith(3, '/reports/daily');
  });
});
