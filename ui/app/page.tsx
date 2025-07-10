'use client'

import { useState } from 'react'
import Chat from '@/components/Chat'
import CasesView from '@/components/CasesView'
import { UserMenu } from '@/components/auth/user-menu'
import { ProtectedRoute } from '@/components/auth/protected-route'
import { useAuth } from '@/lib/auth-context'
import { MessageSquare, Briefcase, FileText, Calendar, Menu, X, Shield } from 'lucide-react'
import DocumentsPage from './documents/page'
import AdminPage from './admin/page'

export default function Home() {
  const [activeTab, setActiveTab] = useState('chat')
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)
  const { user } = useAuth()

  const navigationItems = [
    { id: 'chat', label: 'Chat', icon: MessageSquare },
    { id: 'cases', label: 'Sprawy', icon: Briefcase },
    { id: 'documents', label: 'Dokumenty', icon: FileText },
    { id: 'deadlines', label: 'Terminy', icon: Calendar },
  ]
  
  // Add admin panel for admin users
  if (user?.role === 'admin') {
    navigationItems.push({ id: 'admin', label: 'Panel Admina', icon: Shield })
  }

  const handleTabClick = (tabId: string) => {
    console.log('Handler: handleTabClick', { tabId });
    setActiveTab(tabId);
  };

  const handleSidebarToggle = () => {
    console.log('Handler: handleSidebarToggle');
    setIsSidebarOpen(!isSidebarOpen);
  };

  return (
    <ProtectedRoute>
      <div className="flex h-screen">
      {/* Sidebar */}
      <aside
        className={`${
          isSidebarOpen ? 'w-64' : 'w-0'
        } bg-gray-900 text-white transition-all duration-300 overflow-hidden`}
      >
        <div className="p-4">
          <h1 className="text-2xl font-bold mb-8">AI Paralegal</h1>
          <nav className="space-y-2">
            {navigationItems.map((item) => {
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  onClick={() => handleTabClick(item.id)}
                  className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors ${
                    activeTab === item.id
                      ? 'bg-primary text-white'
                      : 'hover:bg-gray-800'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  <span>{item.label}</span>
                </button>
              )
            })}
          </nav>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Top Bar */}
        <header className="bg-white shadow-sm border-b px-4 py-3 flex items-center justify-between">
          <button
            onClick={handleSidebarToggle}
            className="p-2 hover:bg-gray-100 rounded-lg"
          >
            {isSidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          
          <UserMenu />
        </header>

        {/* Content Area */}
        <main className="flex-1 p-6 bg-gray-50">
          {activeTab === 'chat' && (
            <div className="h-full">
              <Chat />
            </div>
          )}
          
          {activeTab === 'cases' && <CasesView />}
          
          {activeTab === 'documents' && <DocumentsPage />}
          
          {activeTab === 'deadlines' && (
            <div className="bg-white rounded-lg shadow-lg p-6">
              <h2 className="text-2xl font-semibold mb-4">Terminy i przypomnienia</h2>
              <p className="text-gray-600">Funkcja w przygotowaniu...</p>
            </div>
          )}
          
          {activeTab === 'admin' && <AdminPage />}
        </main>
      </div>
    </div>
    </ProtectedRoute>
  )
}
