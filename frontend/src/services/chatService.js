import apiClient from './apiClient';

/**
 * 发送对话消息（统一编排入口）
 * 后端自动根据意图执行：生成报表 / 回答澄清 / 状态查询
 */
export const sendMessage = (reportDate, message, sessionId = null, baselineDate = null) => {
  const body = { report_date: reportDate, message };
  if (sessionId) body.session_id = sessionId;
  if (baselineDate) body.baseline_date = baselineDate; // 生成日报时的链式基线日（默认=最近一份日报，通常昨日）
  return apiClient.post('/chat', body);
};

/**
 * 获取对话历史
 * @param {string|null} reportDate - 按报告日期查询
 * @param {string|null} sessionId - 按会话 ID 查询（优先级高于 reportDate）
 */
export const getChatHistory = (reportDate = null, sessionId = null) => {
  const params = {};
  if (sessionId) params.session_id = sessionId;
  else if (reportDate) params.report_date = reportDate;
  return apiClient.get('/chat/history', { params });
};
