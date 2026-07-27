import apiClient from './apiClient';

/** 「口径与设置」页：计算字典与规则 */
export const getConfig = () =>
  apiClient.get('/config');
