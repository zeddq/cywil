'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, FileText, Calendar, Briefcase } from 'lucide-react'
import { api } from '@/lib/api/client'
import type { ChatMessage, ChatResponse } from '@/lib/types'

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await api.chat.send({ message: input })
      
      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.response,
        timestamp: new Date(),
        citations: response.citations,
        documents: response.documents,
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (error) {
      console.error('Chat error:', error)
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Przepraszam, wystąpił błąd. Spróbuj ponownie.',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-lg">
      {/* Header */}
      <div className="p-4 border-b">
        <h2 className="text-xl font-semibold text-gray-800">Asystent Prawny AI</h2>
        <p className="text-sm text-gray-600">Pomoc w sprawach prawa cywilnego</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <p className="text-gray-500 mb-4">
              Witaj! Jestem asystentem prawnym AI specjalizującym się w polskim prawie cywilnym.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-2xl mx-auto">
              <button
                onClick={() => setInput('Jakie są terminy przedawnienia roszczeń?')}
                className="p-3 border rounded-lg hover:bg-gray-50 text-left"
              >
                <Calendar className="w-5 h-5 text-primary mb-2" />
                <p className="text-sm font-medium">Terminy przedawnienia</p>
              </button>
              <button
                onClick={() => setInput('Jak złożyć pozew o zapłatę?')}
                className="p-3 border rounded-lg hover:bg-gray-50 text-left"
              >
                <FileText className="w-5 h-5 text-primary mb-2" />
                <p className="text-sm font-medium">Pozew o zapłatę</p>
              </button>
              <button
                onClick={() => setInput('Jakie są moje prawa jako konsument?')}
                className="p-3 border rounded-lg hover:bg-gray-50 text-left"
              >
                <Briefcase className="w-5 h-5 text-primary mb-2" />
                <p className="text-sm font-medium">Prawa konsumenta</p>
              </button>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-4 ${
                message.role === 'user'
                  ? 'bg-primary text-white'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              
              {message.citations && message.citations.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-300">
                  <p className="text-sm font-semibold mb-2">Podstawa prawna:</p>
                  {message.citations.map((citation, idx) => (
                    <div key={idx} className="text-sm mb-1">
                      <span className="font-medium">{citation.article} {citation.source}</span>
                      {citation.text && <p className="text-xs mt-1 opacity-80">{citation.text}</p>}
                    </div>
                  ))}
                </div>
              )}

              {message.documents && message.documents.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-300">
                  <p className="text-sm font-semibold mb-2">Dokumenty:</p>
                  {message.documents.map((doc, idx) => (
                    <a
                      key={idx}
                      href={doc.url}
                      className="text-sm text-blue-600 hover:underline block"
                    >
                      📄 {doc.name}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg p-4">
              <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t">
        <div className="flex space-x-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Zadaj pytanie prawne..."
            className="flex-1 p-3 border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary"
            rows={2}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  )
}