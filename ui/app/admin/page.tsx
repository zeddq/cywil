'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import UserManagement from '@/components/admin/UserManagement'
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Shield } from 'lucide-react'

export default function AdminPage() {
  const { user, loading } = useAuth()
  const router = useRouter()
  const [isAuthorized, setIsAuthorized] = useState(false)

  useEffect(() => {
    if (!loading) {
      if (!user || user.role !== 'admin') {
        router.push('/')
      } else {
        setIsAuthorized(true)
      }
    }
  }, [user, loading, router])

  if (loading || !isAuthorized) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Shield className="h-12 w-12 text-gray-400 mx-auto mb-4" />
          <p className="text-gray-500">Verifying admin access...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Admin Panel</h1>
        <p className="text-gray-600">Manage system users and permissions</p>
      </div>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>User Management</CardTitle>
            <CardDescription>
              View and manage all registered users, their roles, and access permissions
            </CardDescription>
          </CardHeader>
          <UserManagement />
        </Card>
      </div>
    </div>
  )
}