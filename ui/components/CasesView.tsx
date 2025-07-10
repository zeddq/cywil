'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import type { Case } from '@/lib/types'
import CaseDetails from './CaseDetails'
import NewCaseForm from './NewCaseForm'
import { ChevronDown, Plus } from 'lucide-react'

export default function CasesView() {
  const [cases, setCases] = useState<Case[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null)
  const [updatingCaseId, setUpdatingCaseId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    const fetchCases = async () => {
      try {
        setLoading(true)
        const casesData = await api.cases.list()
        setCases(casesData)
        setError(null)
      } catch (err) {
        setError('Failed to fetch cases. Please try again later.')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    fetchCases()
  }, [])

  const handleToggleExpand = (caseId: string) => {
    console.log('Handler: handleToggleExpand', { caseId });
    setExpandedCaseId((prev) => (prev === caseId ? null : caseId))
  }

  const handleUpdateCase = async (caseId: string, updatedData: Partial<Case>) => {
    console.log('Handler: handleUpdateCase', { caseId, updatedData });
    const originalCases = [...cases]
    const optimisticCase = cases.find((c) => c.id === caseId)
    if (!optimisticCase) return

    const updatedCase = { ...optimisticCase, ...updatedData }

    setCases((prevCases) =>
      prevCases.map((c) => (c.id === caseId ? updatedCase : c))
    )
    setUpdatingCaseId(caseId)

    try {
      const freshUpdatedCase = await api.cases.update(caseId, updatedCase)
      setCases((prevCases) =>
        prevCases.map((c) => (c.id === caseId ? freshUpdatedCase : c))
      )
      console.log('Handler: handleUpdateCase success', freshUpdatedCase);
    } catch (err) {
      setError('Failed to update case. Please try again later.')
      console.error(err)
      // Revert on error
      setCases(originalCases)
      console.log('Handler: handleUpdateCase reverted after error', { caseId });
    } finally {
      setUpdatingCaseId(null)
    }
  }

  const handleSaveNewCase = async (newCaseData: Omit<Case, 'id' | 'created_at' | 'updated_at'>) => {
    console.log('Handler: handleSaveNewCase', { newCaseData });
    setIsSaving(true)
    try {
      const newCase = await api.cases.create(newCaseData as Case)
      setCases((prevCases) => [newCase, ...prevCases])
      setIsCreating(false)
      setError(null)
    } catch (err) {
      setError('Failed to create case. Please try again later.')
      console.error(err)
    } finally {
      setIsSaving(false)
    }
  }

  if (loading) {
    return <div className="p-4">Loading cases...</div>
  }

  if (error) {
    return <div className="p-4 text-red-500">{error}</div>
  }

  return (
    <div className="p-4 bg-white rounded-lg shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Zarządzanie sprawami</h1>
        <button
          onClick={() => setIsCreating(!isCreating)}
          className="flex items-center px-4 py-2 text-sm font-medium text-white bg-primary rounded-md hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
        >
          <Plus className="w-5 h-5 mr-2" />
          {isCreating ? 'Anuluj' : 'Nowa sprawa'}
        </button>
      </div>

      {isCreating && (
        <NewCaseForm
          onSave={handleSaveNewCase}
          onCancel={() => setIsCreating(false)}
          isSaving={isSaving}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start mt-6">
        {cases.map((caseItem) => (
          <div key={caseItem.id} className="border rounded-lg p-4 shadow flex flex-col justify-between">
            <div onClick={() => handleToggleExpand(caseItem.id)} className="cursor-pointer">
              <div className="flex justify-between items-start mb-2">
                <h2 className="text-xl font-semibold">{caseItem.title}</h2>
                <div className="flex items-center">
                  <span
                    className={`px-2 py-1 text-xs font-semibold rounded-full capitalize ${
                      caseItem.status === 'active'
                        ? 'bg-green-100 text-green-800'
                        : caseItem.status === 'closed'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {caseItem.status}
                  </span>
                  <ChevronDown
                    className={`w-5 h-5 ml-2 transition-transform ${
                      expandedCaseId === caseItem.id ? 'rotate-180' : ''
                    }`}
                  />
                </div>
              </div>
              <p className="text-gray-600 text-sm break-words mb-4">
                {caseItem.description}
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-800">
                <strong>Klient:</strong> {caseItem.client_name}
              </p>
              <p className="text-sm text-gray-500 mt-2">
                <strong>Sygnatura:</strong> {caseItem.reference_number}
              </p>
              <p className="text-xs text-gray-400 mt-4">
                Utworzono: {new Date(caseItem.created_at).toLocaleDateString()}
              </p>
            </div>
            {expandedCaseId === caseItem.id && (
              <CaseDetails 
                caseItem={caseItem}
                onUpdate={handleUpdateCase}
                isUpdating={updatingCaseId === caseItem.id}
              />
            )}
          </div>
        ))}
      </div>
      {cases.length === 0 && !isCreating && <p>No cases found.</p>}
    </div>
  )
} 
