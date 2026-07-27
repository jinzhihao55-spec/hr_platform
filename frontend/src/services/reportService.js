import apiClient from './apiClient';

// ========== 生成 ==========

/** 生成日报 */
export const generateDaily = (reportDate) =>
  apiClient.post('/reports/daily', { report_date: reportDate });

/** 生成周报 */
export const generateWeekly = (weekStart, weekEnd) =>
  apiClient.post('/reports/weekly', { week_start: weekStart, week_end: weekEnd });

// ========== 基线 ==========

/**
 * 检查链式基线日报是否已落库（能否链式生成当日日报）
 * @param {string} reportDate - 报告日
 * @param {string|null} baselineDate - 可选：待校验的基线日；缺省=报告日前一工作日
 */
export const checkDailyExists = (reportDate, baselineDate = null) =>
  apiClient.get(`/reports/daily/${reportDate}/exists`,
    baselineDate ? { params: { baseline_date: baselineDate } } : undefined);

/** 上传定稿日报 xlsx，并登记为下一 Run 的不可变正式基线。 */
export const importDaily = (reportDate, file) => {
  const formData = new FormData();
  formData.append('report_date', reportDate);
  formData.append('file', file);
  return apiClient.post('/reports/daily/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
};

// ========== 选择器 ==========

/** 日报日期选择器：已生成日报的日期列表（倒序） */
export const getDailyDates = () =>
  apiClient.get('/reports/daily/dates');

/** 周报周次选择器：已生成周报的周次列表（倒序） */
export const getWeeklyWeeks = () =>
  apiClient.get('/reports/weekly/weeks');

// ========== 结构化视图 ==========

/** 日报结构化视图（Row2-40 + 在岗时长 + 校验 + KPI） */
export const getDailyView = (reportDate) =>
  apiClient.get(`/reports/daily/${reportDate}/view`);

/** 周报结构化视图（Sheet2 主体×事业部 + Sheet1 成本中心×项目） */
export const getWeeklyView = (weekStart, weekEnd) =>
  apiClient.get(`/reports/weekly/${weekEnd}/view`, { params: { week_start: weekStart } });

// ========== 下载 ==========

/** 按服务器路径下载产物文件（日报/周报 xlsx、计算日志 md） */
export const downloadReport = (path) =>
  apiClient.get('/reports/download', { params: { path }, responseType: 'blob' });

// ========== 不可变发布记录（正式链路） ==========

export const getPublishedReports = (reportKind) =>
  apiClient.get(`/reports/${reportKind}`);

export const getPublishedReport = (reportId) =>
  apiClient.get(`/reports/${reportId}`);

export const downloadPublishedArtifact = (reportId, artifactKind = 'excel') =>
  apiClient.get(
    `/reports/${reportId}/artifacts/${artifactKind}`,
    { responseType: 'blob' },
  );

export const getReadiness = () => apiClient.get('/ready');
