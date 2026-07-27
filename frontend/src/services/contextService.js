import apiClient from './apiClient';

// ========== 工作台上下文 ==========

/** 获取工作台上下文：报告日期、星期、主表行数、待确认澄清数等 */
export const getContext = (reportDate) =>
  apiClient.get('/context', { params: { report_date: reportDate } });

// ========== 文件上传入库 ==========

/** 上传四类结构化输入文件 */
export const uploadFiles = (reportDate, files) => {
  const formData = new FormData();
  formData.append('report_date', reportDate);
  if (files.employees) formData.append('employees', files.employees);
  if (files.resignations) formData.append('resignations', files.resignations);
  if (files.agreements) formData.append('agreements', files.agreements);
  if (files.recruitment) formData.append('recruitment', files.recruitment);
  // 基线日报走单独导入接口 POST /reports/daily/import，不通过 /ingest
  return apiClient.post('/ingest', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    // 截图走 OCR（PaddleOCR / DeepSeek）可能远超默认 60s
    timeout: 300000,
  });
};

// ========== 自然语言查询 ==========

/** 自然语言 → AI 生成 SQL → 查库返回结果 */
export const askQuery = (question, schemaHint = '', maxRows = 1000) =>
  apiClient.post('/query', {
    question,
    schema_hint: schemaHint,
    max_rows: maxRows,
  });
