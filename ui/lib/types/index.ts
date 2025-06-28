export interface ChatMessage {
  id: string
  thread_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  citations?: Citation[]
  documents?: Document[]
}

export interface Citation {
  article: string
  text: string
  source: 'KC' | 'KPC'
}

export interface Document {
  id: string
  case_id: string
  document_type: string
  title: string
  file_path?: string
  content?: string
  document_metadata?: Record<string, any>
  citations?: Record<string, any>
  key_dates?: Record<string, any>
  status: 'draft' | 'final' | 'filed'
  filed_date?: string // Using string for ISO date format
  created_at: string
  updated_at?: string
}

export interface Case {
  id: string
  case_number: string
  title: string
  description?: string
  status: 'active' | 'closed' | 'archived'
  case_type?: string
  client_name: string
  client_contact: Record<string, any>
  opposing_party?: string
  opposing_party_contact?: Record<string, any>
  court_name?: string
  court_case_number?: string
  judge_name?: string
  amount_in_dispute?: number
  currency?: string
  created_at: string
  updated_at?: string
  closed_at?: string
  documents?: Document[]
  deadlines?: Deadline[]
  notes?: Note[]
}

export interface Deadline {
  id: string
  case_id: string
  deadline_type: string
  description?: string
  due_date: string
  legal_basis?: string
  is_court_deadline: boolean
  is_extendable: boolean
  status: 'pending' | 'completed' | 'missed'
  completed_at?: string
  reminder_days_before: number
  reminder_sent: boolean
  created_at: string
  updated_at?: string
}

export interface Note {
  id: string
  case_id: string
  note_type: string
  subject?: string
  content: string
  duration_minutes?: number
  billable: boolean
  created_at: string
  updated_at?: string
}

export interface ChatRequest {
  message: string
  thread_id?: string
  case_id?: string
}

export interface ChatResponse {
  response: string
  thread_id: string
  status: string
  citations?: Citation[]
  documents?: Document[]
  suggested_actions?: string[]
}

export interface ChatStreamResponse {
  type: 'text_chunk' | 'tool_call_start' | 'tool_call_complete' | 'full_message'
  content: {
    name?: string
    call_id?: string
    output?: string
  }[] | string
  thread_id: string
  status: 'streaming' | 'error' | 'success'
}
