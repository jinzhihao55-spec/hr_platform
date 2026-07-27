import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 从各种后端错误响应形态中提取可读信息
// 支持：{detail} / {message} / {error: {message}} / {status: "needs_clarification", error: {...}}
function extractMessage(data) {
  if (!data || typeof data !== 'object') return null;
  if (typeof data.detail === 'string') return data.detail;
  if (typeof data.message === 'string') return data.message;
  if (data.error && typeof data.error === 'object') {
    return data.error.message || data.error.code || null;
  }
  return null;
}

// 响应拦截器：统一处理错误
apiClient.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    let data = error.response?.data;
    // responseType: 'blob' 时错误体也是 Blob，需要先转回 JSON
    if (data instanceof Blob && data.type?.includes('json')) {
      try {
        data = JSON.parse(await data.text());
      } catch {
        data = null;
      }
    }
    const message =
      extractMessage(data) ||
      error.message ||
      '请求失败，请稍后重试';
    const err = new Error(message);
    err.status = error.response?.status;
    err.data = data; // 保留原始响应体，供调用方读取澄清详情等
    console.error('[API Error]', message);
    return Promise.reject(err);
  }
);

export default apiClient;
