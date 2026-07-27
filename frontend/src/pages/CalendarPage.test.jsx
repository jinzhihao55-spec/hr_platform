import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CalendarPage from './CalendarPage';
import { getCalendarMonth, openCalendarDate } from '../services/calendarService';

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../services/calendarService', () => ({
  getCalendarMonth: vi.fn(),
  openCalendarDate: vi.fn(),
}));

const calendarData = {
  month: '2026-07',
  days: [
    {
      date: '2026-07-15',
      is_workday: true,
      run_id: 'run-15',
      run_status: 'awaiting_decision',
      daily_status: 'pending',
      weekly_status: null,
    },
    {
      date: '2026-07-16',
      is_workday: true,
      run_id: null,
      run_status: null,
      daily_status: null,
      weekly_status: null,
    },
    {
      date: '2026-07-08',
      is_workday: true,
      run_id: 'run-08',
      run_status: 'ready',
      daily_status: 'published',
      weekly_status: 'not_due',
    },
    {
      date: '2026-07-20',
      is_workday: true,
      run_id: 'stale-empty-run-20',
      run_status: 'created',
      daily_status: 'draft',
      weekly_status: 'not_due',
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <CalendarPage initialMonth="2026-07" />
    </MemoryRouter>,
  );
}

describe('CalendarPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    getCalendarMonth.mockResolvedValue(calendarData);
    openCalendarDate.mockResolvedValue({ id: 'run-16' });
  });

  it('opens the selected date run from calendar status data', async () => {
    const user = userEvent.setup();
    renderPage();

    const dayButton = await screen.findByRole('button', {
      name: /7月15日.*待确认/,
    });
    await user.click(dayButton);

    expect(mockNavigate).toHaveBeenCalledWith('/runs/run-15');
  });

  it('creates a provisional run before opening an empty workday', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', {
      name: /7月16日.*未开始/,
    }));

    expect(openCalendarDate).toHaveBeenCalledWith('2026-07-16');
    expect(mockNavigate).toHaveBeenCalledWith('/runs/run-16');
  });

  it('rematches the baseline before opening an existing empty run', async () => {
    openCalendarDate.mockResolvedValueOnce({ id: 'rebased-run-20' });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', {
      name: /7月20日.*待上传/,
    }));

    expect(openCalendarDate).toHaveBeenCalledWith('2026-07-20');
    expect(mockNavigate).toHaveBeenCalledWith('/runs/rebased-run-20');
  });

  it('exposes month navigation with accessible labels', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('2026年7月');
    await user.click(screen.getByRole('button', { name: '下个月' }));

    expect(getCalendarMonth).toHaveBeenLastCalledWith('2026-08');
  });

  it('labels a midweek weekly target as not due instead of failed', async () => {
    renderPage();

    const dayButton = await screen.findByRole('button', {
      name: /7月8日.*周报 未到周报日/,
    });

    expect(dayButton).toHaveTextContent('周报 未到周报日');
    expect(dayButton).not.toHaveTextContent('失败');
    expect(within(dayButton).getByText('周报 未到周报日')).toHaveAttribute(
      'title',
      '周报 未到周报日',
    );
  });

  it('labels a completed daily run as published instead of still previewable', async () => {
    renderPage();

    expect(await screen.findByRole('button', {
      name: /7月8日，已发布，日报 已发布/,
    })).toBeVisible();
  });
});
