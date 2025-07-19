import axios from 'axios'
import type { ChatRequest, ChatResponse, Case, Document, Deadline, ChatStreamResponse, User, UserUpdate, UserListResponse } from '@/lib/types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api'

const axiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add request interceptor to include auth token
axiosInstance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Add response interceptor to handle auth errors
axiosInstance.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);


export const apiClient = {
  // Admin endpoints
  getAdminUsers: async (): Promise<UserListResponse> => {
    const { data } = await axiosInstance.get<UserListResponse>('/api/auth/admin/users')
    return data
  },
  
  updateUser: async (userId: string, updates: UserUpdate): Promise<User> => {
    const { data } = await axiosInstance.patch<User>(`/api/auth/admin/users/${userId}`, updates)
    return data
  },
  
  deleteUser: async (userId: string): Promise<void> => {
    await axiosInstance.delete(`/api/auth/admin/users/${userId}`)
  },
}

export const api = {
  // Chat endpoints
  chat: {
    send: async (request: ChatRequest): Promise<ChatResponse> => {
      console.log('API Call: chat.send', { request });
      const { data } = await axiosInstance.post<ChatResponse>('/chat', request)
      console.log('API Response: chat.send', { data });
      return data
    },
    
    stream: async function* (request: ChatRequest): AsyncGenerator<ChatStreamResponse, void, unknown> {
      console.log('API Call: chat.stream', { request });
      
      const token = localStorage.getItem('access_token');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };
      
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response body reader available');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('}\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk: ChatStreamResponse = JSON.parse(line + '}');
                // console.log('API Stream chunk:', chunk);
                yield chunk;
              } catch (e) {
                console.error('Failed to parse stream chunk:', line, e);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    },
  },

  // Case management
  cases: {
    list: async (): Promise<Case[]> => {
      console.log('API Call: cases.list');
      // The API returns a nested structure, so we transform it to match our `Case` type.
      const { data } = await axiosInstance.get<Case[]>('/cases')
      console.log('API Response: cases.list', data );
      return data;
    },
    get: async (id: string): Promise<Case> => {
      console.log('API Call: cases.get', { id });
      // The API returns a nested structure, so we transform it to match our `Case` type.
      const { data } = await axiosInstance.get<Case>(`/cases/${id}`)
      console.log('API Response: cases.get', data);
      return data;
    },
    create: async (caseData: Omit<Case, 'id' | 'created_at' | 'updated_at'>): Promise<Case> => {
      console.log('API Call: cases.create with payload:', caseData);
      const { data } = await axiosInstance.post<Case>('/cases', caseData)
      console.log('API Response: cases.create', data);
      return data
    },
    update: async (id: string, updatedCase: Case): Promise<Case> => {
      console.log(`API Call: cases.update for id: ${id} with payload:`, updatedCase);
      const { data } = await axiosInstance.put<Case>(`/cases/${id}`, updatedCase)
      console.log('API Response: cases.update', data);
      return data
    },
  },

  // Document management
  documents: {
    upload: async (caseId: string, file: File): Promise<{ filename: string; status: string; document_id: string; case_id: string }> => {
      console.log('API Call: documents.upload', { fileName: file.name, caseId });
      const formData = new FormData()
      formData.append('file', file)

      const { data } = await axios.post<{ filename: string; status: string; document_id: string; case_id: string }>(`${API_BASE_URL}/upload/${caseId}`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })
      console.log('API Response: documents.upload', { data });
      return data
    },
    list: async (caseId?: string): Promise<Document[]> => {
      console.log('API Call: documents.list', { caseId });
      const params = caseId ? { case_id: caseId } : {}
      const { data } = await axiosInstance.get<Document[]>('/documents', { params })
      console.log('API Response: documents.list', { data });
      return data
    },
    get: async (id: string): Promise<Document> => {
      console.log('API Call: documents.get', { id });
      const { data } = await axiosInstance.get<Document>(`/documents/${id}`)
      console.log('API Response: documents.get', { data });
      return data
    },
    create: async (documentData: Partial<Document>): Promise<Document> => {
      console.log('API Call: documents.create', { documentData });
      const { data } = await axiosInstance.post<Document>('/documents', documentData)
      console.log('API Response: documents.create', { data });
      return data
    },
  },

  // Deadline management
  deadlines: {
    list: async (caseId?: string): Promise<Deadline[]> => {
      console.log('API Call: deadlines.list', { caseId });
      const params = caseId ? { case_id: caseId } : {}
      const { data } = await axiosInstance.get<Deadline[]>('/deadlines', { params })
      console.log('API Response: deadlines.list', { data });
      return data
    },
    create: async (deadline: Partial<Deadline>): Promise<Deadline> => {
      console.log('API Call: deadlines.create', { deadline });
      const { data } = await axiosInstance.post<Deadline>('/deadlines', deadline)
      console.log('API Response: deadlines.create', { data });
      return data
    },
    update: async (id: string, deadline: Partial<Deadline>): Promise<Deadline> => {
      console.log('API Call: deadlines.update', { id, deadline });
      const { data } = await axiosInstance.put<Deadline>(`/deadlines/${id}`, deadline)
      console.log('API Response: deadlines.update', { data });
      return data
    },
  },

  // Search
  search: {
    query: async (query: string, filters?: any): Promise<any> => {
      console.log('API Call: search.query', { query, filters });
      const { data } = await axiosInstance.post('/query', { query, ...filters })
      console.log('API Response: search.query', { data });
      return data
    },
  },
}
