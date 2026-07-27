import apiClient from './apiClient';

// ========== 任务状态 ==========

/** 获取单个任务状态 */
export const getJob = (jobId) =>
  apiClient.get(`/jobs/${jobId}`);

/** 获取最近的任务列表 */
export const listJobs = () =>
  apiClient.get('/jobs');

// ========== 澄清事项 ==========

/** 列出某报告日的待确认事项 */
export const getClarifications = (reportDate, includeAnswered = false) =>
  apiClient.get('/clarifications', {
    params: { report_date: reportDate, include_answered: includeAnswered },
  });

/** 提交某条澄清的答复 */
export const answerClarification = (itemId, answer) =>
  apiClient.post(`/clarifications/${itemId}/answer`, { answer });
