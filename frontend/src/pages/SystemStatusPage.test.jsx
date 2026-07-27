import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SystemStatusPage from './SystemStatusPage';
import { getReadiness } from '../services/reportService';

vi.mock('../services/reportService', () => ({
  getReadiness: vi.fn(),
}));

describe('SystemStatusPage', () => {
  beforeEach(() => {
    getReadiness.mockReset();
  });

  it('renders actionable component diagnostics when readiness fails', async () => {
    const error = new Error('服务尚未就绪');
    error.status = 503;
    error.data = {
      status: 'not_ready',
      mysql: false,
      redis: true,
      migration: false,
      output: true,
      config: false,
    };
    getReadiness.mockRejectedValue(error);

    render(
      <MemoryRouter>
        <SystemStatusPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('MySQL 数据库')).toBeVisible();
    expect(screen.getByText('检查数据库连接与凭据')).toBeVisible();
    expect(screen.getByText('运行数据库迁移')).toBeVisible();
    expect(screen.getByText('补齐生产环境变量')).toBeVisible();
    expect(screen.getByRole('button', { name: '重新检查' })).toBeEnabled();
  });
});
