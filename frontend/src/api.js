import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api', timeout: 8000 })
api.interceptors.request.use(config => {
  const token = localStorage.getItem('thermosense-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401 && !error.config?.url?.endsWith('/auth/login')) {
    localStorage.removeItem('thermosense-token')
    window.dispatchEvent(new Event('thermosense-auth-expired'))
  }
  return Promise.reject(error)
})
export const login = credentials => api.post('/auth/login', credentials).then(r => r.data)
export const getMe = () => api.get('/auth/me').then(r => r.data)
export const getManagedUsers = () => api.get('/users').then(r => r.data)
export const createManagedUser = account => api.post('/users', account).then(r => r.data)
export const getOverview = () => api.get('/dashboard/overview').then(r => r.data)
export const getLatest = () => api.get('/monitoring/users').then(r => r.data)
export const getReadings = (params = {}) => api.get('/readings', { params }).then(r => r.data)
export const getAlerts = (params = {}) => api.get('/alerts', { params }).then(r => r.data)
export const getFog = () => api.get('/fog/stats').then(r => r.data)
export const getSimulation = () => api.get('/simulation/status').then(r => r.data)
export const startSimulation = config => api.post('/simulation/start', config).then(r => r.data)
export const stopSimulation = () => api.post('/simulation/stop').then(r => r.data)
export const resolveAlert = id => api.patch(`/alerts/${id}/resolve`).then(r => r.data)
export const getUser = id => api.get(`/users/${id}`).then(r => r.data)
export const getAnalytics = () => api.get('/analytics/summary').then(r => r.data)
export const getBlocks = (params = {}) => api.get('/blockchain/records', { params }).then(r => r.data)
export const verifyBlockchain = () => api.get('/blockchain/verify').then(r => r.data)
export default api
