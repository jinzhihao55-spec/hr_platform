import apiClient from './apiClient';

/** 归档页：按报告日期归类的产物文件列表 */
export const getArchives = (kind = 'all') =>
  apiClient.get('/archive', { params: { kind } });
