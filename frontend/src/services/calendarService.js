import apiClient from './apiClient';

export function getCalendarMonth(month) {
  return apiClient.get('/calendar', { params: { month } });
}

export async function openCalendarDate(reportDate) {
  const response = await apiClient.post('/runs', {
    report_date: reportDate,
  });
  return response.run;
}
