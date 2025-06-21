import axios from 'axios'
import type { ChatRequest, ChatResponse, Case, Document, Deadline } from '@/lib/types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const api = {
  // Chat endpoints
  chat: {
    send: async (request: ChatRequest): Promise<ChatResponse> => {
      console.log('API Call: chat.send', { request });
      const { data } = await apiClient.post<ChatResponse>('/chat', request)
      console.log('API Response: chat.send', { data });
      return data
    },
  },

  // Case management
  cases: {
    list: async (): Promise<Case[]> => {
      console.log('API Call: cases.list');
      // The API returns a nested structure, so we transform it to match our `Case` type.
      const { data } = await apiClient.get<Case[]>('/cases')
      console.log('API Response: cases.list', data );
      return data;
    },
    get: async (id: string): Promise<Case> => {
      console.log('API Call: cases.get', { id });
      // The API returns a nested structure, so we transform it to match our `Case` type.
      const { data } = await apiClient.get<Case>(`/cases/${id}`)
      console.log('API Response: cases.get', data);
      return data;
    },
    create: async (caseData: Partial<Case>): Promise<Case> => {
      console.log('API Call: cases.create with payload:', caseData);
      const { data } = await apiClient.post<{ case: Case }>('/cases', caseData)
      console.log('API Response: cases.create', data);
      return data.case
    },
    update: async (id: string, updatedCase: Case): Promise<Object> => {
      console.log(`API Call: cases.update for id: ${id} with payload:`, updatedCase);
      const { data } = await apiClient.put<{ caseData: Object }>(`/cases/${id}`, updatedCase)
      console.log('API Response: cases.update', data);
      return data
    },
  },

  // Document management
  documents: {
    upload: async (file: File, caseId?: string): Promise<Document> => {
      console.log('API Call: documents.upload', { fileName: file.name, caseId });
      const formData = new FormData()
      formData.append('file', file)
      if (caseId) {
        formData.append('case_id', caseId)
      }

      const { data } = await apiClient.post<Document>('/upload', formData, {
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
      const { data } = await apiClient.get<Document[]>('/documents', { params })
      console.log('API Response: documents.list', { data });
      return data
    },
    get: async (id: string): Promise<Document> => {
      console.log('API Call: documents.get', { id });
      const { data } = await apiClient.get<Document>(`/documents/${id}`)
      console.log('API Response: documents.get', { data });
      return data
    },
  },

  // Deadline management
  deadlines: {
    list: async (caseId?: string): Promise<Deadline[]> => {
      console.log('API Call: deadlines.list', { caseId });
      const params = caseId ? { case_id: caseId } : {}
      const { data } = await apiClient.get<Deadline[]>('/deadlines', { params })
      console.log('API Response: deadlines.list', { data });
      return data
    },
    create: async (deadline: Partial<Deadline>): Promise<Deadline> => {
      console.log('API Call: deadlines.create', { deadline });
      const { data } = await apiClient.post<Deadline>('/deadlines', deadline)
      console.log('API Response: deadlines.create', { data });
      return data
    },
    update: async (id: string, deadline: Partial<Deadline>): Promise<Deadline> => {
      console.log('API Call: deadlines.update', { id, deadline });
      const { data } = await apiClient.put<Deadline>(`/deadlines/${id}`, deadline)
      console.log('API Response: deadlines.update', { data });
      return data
    },
  },

  // Search
  search: {
    query: async (query: string, filters?: any): Promise<any> => {
      console.log('API Call: search.query', { query, filters });
      const { data } = await apiClient.post('/query', { query, ...filters })
      console.log('API Response: search.query', { data });
      return data
    },
  },
}
