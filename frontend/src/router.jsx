import { createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import Archive from './pages/Archive';
import CalendarPage from './pages/CalendarPage';
import ComputeLog from './pages/ComputeLog';
import DailyReport from './pages/DailyReport';
import Settings from './pages/Settings';
import WeeklyReport from './pages/WeeklyReport';
import RunWorkspacePage from './pages/RunWorkspacePage';
import RunPreviewPage from './pages/RunPreviewPage';
import SystemStatusPage from './pages/SystemStatusPage';

export const router = createBrowserRouter([
  {
    element: <ErrorBoundary><App /></ErrorBoundary>,
    children: [
      { index: true, element: <Navigate to="/calendar" replace /> },
      { path: 'calendar', element: <CalendarPage /> },
      { path: 'runs/:runId', element: <RunWorkspacePage /> },
      { path: 'runs/:runId/preview', element: <RunPreviewPage /> },
      { path: 'reports/daily', element: <DailyReport /> },
      { path: 'reports/weekly', element: <WeeklyReport /> },
      { path: 'history', element: <Archive /> },
      { path: 'settings', element: <Settings /> },
      { path: 'logs', element: <ComputeLog /> },
      { path: 'system', element: <SystemStatusPage /> },
      { path: '*', element: <Navigate to="/calendar" replace /> },
    ],
  },
]);
