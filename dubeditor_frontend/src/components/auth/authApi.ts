/**
 * Auth API + types.
 */
import api from '../../api'

export interface User {
  id: number
  username: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface UserWithCount extends User {
  project_count: number
}

export const authApi = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }).then(r => r.data as { user: User }),

  logout: () =>
    api.post('/auth/logout').then(r => r.data),

  me: () =>
    api.get('/auth/me').then(r => r.data as { user: User | null }),

  changePassword: (oldPassword: string, newPassword: string) =>
    api.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    }).then(r => r.data),
}

export const adminApi = {
  listUsers: () =>
    api.get('/admin/users').then(r => r.data as UserWithCount[]),

  createUser: (data: { username: string; password: string; display_name?: string; is_admin?: boolean }) =>
    api.post('/admin/users', data).then(r => r.data as User),

  updateUser: (id: number, data: Partial<Pick<User, 'display_name' | 'is_admin' | 'is_active'>>) =>
    api.patch(`/admin/users/${id}`, data).then(r => r.data as User),

  deleteUser: (id: number) =>
    api.delete(`/admin/users/${id}`).then(r => r.data as { ok: boolean; orphaned_projects: number; message: string }),

  resetPassword: (id: number, newPassword: string) =>
    api.post(`/admin/users/${id}/reset-password`, { new_password: newPassword }).then(r => r.data),

  listProjects: (filters?: { owner_id?: number; days?: number; orphan_only?: boolean; search?: string }) => {
    const params: any = {}
    if (filters?.owner_id !== undefined) params.owner_id = filters.owner_id
    if (filters?.days !== undefined) params.days = filters.days
    if (filters?.orphan_only) params.orphan_only = true
    if (filters?.search) params.search = filters.search
    return api.get('/admin/projects', { params }).then(r => r.data as AdminProject[])
  },

  transferProject: (projectId: number, newOwnerId: number | null) =>
    api.post(`/admin/projects/${projectId}/transfer`, { new_owner_id: newOwnerId }).then(r => r.data),
}

export interface AdminProject {
  id: number
  name: string
  video_path: string | null
  created_at: string | null
  owner_id: number | null
  owner_username: string | null
  owner_display_name: string | null
  subtitle_count: number
}
