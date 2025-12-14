const MODE = import.meta.env.MODE ?? 'development';

export const isProduction = MODE === 'production';
export const isDevelopment = MODE === 'development' || MODE === 'dev' || (!isProduction && MODE !== 'test');
export const isTest = MODE === 'test';

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? '/api';
