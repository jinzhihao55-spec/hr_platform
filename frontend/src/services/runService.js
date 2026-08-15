import apiClient from './apiClient';

const IMAGE_FILE = /\.(?:bmp|jpe?g|png|tiff?|webp)$/i;
const DEFAULT_LONG_TIMEOUT_MS = 180000;
const VISION_UPLOAD_TIMEOUT_MS = 450000;

export function getRun(runId) {
  return apiClient.get(`/runs/${runId}`, { timeout: 180000 });
}

export function uploadRunSource(runId, sourceType, file) {
  const formData = new FormData();
  formData.append('file', file);
  const imageUpload = file.type.startsWith('image/') || IMAGE_FILE.test(file.name);
  return apiClient.put(`/runs/${runId}/sources/${sourceType}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: imageUpload ? VISION_UPLOAD_TIMEOUT_MS : DEFAULT_LONG_TIMEOUT_MS,
  });
}

export function answerRunDecision(runId, decisionId, answer) {
  return apiClient.post(`/runs/${runId}/decisions/${decisionId}`, {
    answer,
    operator_ref: 'local-operator',
  });
}

export function getDecisionPreview(runId, decisionId) {
  return apiClient.get(`/runs/${runId}/decisions/${decisionId}/preview`);
}

export function getWeeklyReview(runId) {
  return apiClient.get(`/runs/${runId}/weekly/review`);
}

export function createRevisionRun(reportDate) {
  return apiClient.post('/runs', {
    report_date: reportDate,
    create_new: true,
  });
}

export function retryRun(runId) {
  return apiClient.post(`/runs/${runId}/retry`);
}

export function refreshRunState(runId) {
  return apiClient.post(`/runs/${runId}/parse`);
}

export function finalizeRunBaseline(runId, file) {
  const formData = new FormData();
  formData.append('file', file);
  return apiClient.post(`/runs/${runId}/baseline`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
}

export function getRunPreview(runId, reportKind) {
  return apiClient.get(`/runs/${runId}/preview/${reportKind}`, {
    timeout: 180000,
  });
}

export function publishRun(runId, reportKinds) {
  return apiClient.post(`/runs/${runId}/publish`, {
    report_kinds: reportKinds,
    operator_ref: 'local-operator',
  }, {
    timeout: 180000,
  });
}

export function overrideDailyBaseline(reportDate, file) {
  const formData = new FormData();
  formData.append('file', file);
  return apiClient.post(`/reports/daily/${reportDate}/baseline-override`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  });
}
