import axios from 'axios'

// Timeout 5 phút — phù hợp với các API gọi LLM (Pass 1 phân tích phim,
// Pass 3 dịch chunk, Pass 4 QC review) có thể kéo dài.
// Backend httpx timeout là 600s nên FE vẫn nhỏ hơn để tránh treo vô tận.
const api = axios.create({
  baseURL: '/dub/api',
  timeout: 300000, // 5 phút = 300_000 ms
})

export default api
