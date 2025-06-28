import axios from 'axios'
import type { ChatRequest, ChatResponse, Case, Document, Deadline, ChatStreamResponse } from '@/lib/types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api'

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
    
    stream: async function* (request: ChatRequest): AsyncGenerator<ChatStreamResponse, void, unknown> {
      console.log('API Call: chat.stream', { request });
      
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
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
    create: async (caseData: Omit<Case, 'id' | 'created_at' | 'updated_at'>): Promise<Case> => {
      console.log('API Call: cases.create with payload:', caseData);
      const { data } = await apiClient.post<Case>('/cases', caseData)
      console.log('API Response: cases.create', data);
      return data
    },
    update: async (id: string, updatedCase: Case): Promise<Case> => {
      console.log(`API Call: cases.update for id: ${id} with payload:`, updatedCase);
      const { data } = await apiClient.put<Case>(`/cases/${id}`, updatedCase)
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
