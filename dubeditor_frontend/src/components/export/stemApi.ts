/**
 * Stem Separator API client + types.
 */
import api from '../../api'

export interface StemInfo {
  demucs_installed: boolean
  cuda_available: boolean
  device: 'cuda' | 'cpu'
  model: string
  error: string | null
}

export interface StemJobStatus {
  status: 'idle' | 'pending' | 'running' | 'done' | 'error'
  progress: number              // 0-1
  message: string
  result: Record<string, string> | null   // {bass: '/dub/exports/...', drums: ..., vocals: ...}
  error: string | null
}

export const stemApi = {
  info: () => api.get<StemInfo>('/export_video/stem-info').then(r => r.data),

  status: (projectId: number) =>
    api.get<StemJobStatus>(`/export_video/stem-status/${projectId}`).then(r => r.data),

  cache: (projectId: number) =>
    api.get<{ cached: boolean; stems: Record<string, string> }>(
      `/export_video/stem-cache/${projectId}`
    ).then(r => r.data),

  separate: (projectId: number) =>
    api.post(`/export_video/separate-stems/${projectId}`).then(r => r.data),

  clearCache: (projectId: number) =>
    api.delete(`/export_video/stem-cache/${projectId}`).then(r => r.data),
}
