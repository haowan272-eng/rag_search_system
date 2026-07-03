export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface KnowledgeBase {
  id: number
  name: string
  description: string | null
  chunk_config: string | null
  created_by: number
  created_at: string
  updated_at: string
  member_count: number
  role: 'owner' | 'admin' | 'editor' | 'viewer' | null
}

export interface KnowledgeBaseMember {
  user_id: number
  username: string
  role: 'owner' | 'admin' | 'editor' | 'viewer'
  created_at: string
}

export interface DocumentItem {
  id: number
  file_name: string
  content_type: string
  file_size: number
  status: 'uploaded' | 'processing' | 'indexed' | 'failed' | string
  source_retained: boolean
  created_at: string
  uploaded_by: number
  kb_id: number | null
}

export interface Conversation {
  id: number
  title: string
  kb_id: number | null
  created_at: string
  updated_at: string
}

export interface Citation {
  source_id: number
  chunk_id: number
  document_id: number | null
  kb_id: number | null
  filename: string
  chunk_index: number | null
  page_start: number | null
  page_end: number | null
  heading_path: string | null
  source_type: string | null
  location: string | null
  score: number
  quote: string
}

export interface RagAnswer {
  query: string
  answer: string
  conversation_id: number | null
  citations: Citation[]
  retrieved_count: number
  memory_used: MemoryItem[]
  degraded: boolean
  context_compacted: boolean
}

export interface MemoryItem {
  keyword: string
  category: string
  weight: number
}

export interface Message {
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations_json?: string | null
  memory_json?: string | null
  citations?: Citation[]
  memory_used?: MemoryItem[]
  degraded?: boolean
  context_compacted?: boolean
  created_at?: string
  pending?: boolean
  error?: boolean
}
