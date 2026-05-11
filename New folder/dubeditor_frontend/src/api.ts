import axios from 'axios'

const api = axios.create({
  baseURL: '/dub/api',
  timeout: 60000,
})

export default api
