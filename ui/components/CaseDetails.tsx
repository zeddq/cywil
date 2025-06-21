'use client'

import type { Case } from '@/lib/types'
import EditableField from './EditableField'

interface CaseDetailsProps {
  caseItem: Case
  onUpdate: (caseId: string, updatedData: Partial<Case>) => void
  isUpdating: boolean
}

export default function CaseDetails({ caseItem, onUpdate, isUpdating }: CaseDetailsProps) {
  const handleSave = (field: keyof Case, value: string) => {
    console.log('Handler: handleSave in CaseDetails', { caseId: caseItem.id, field, value });
    if (caseItem[field] !== value) {
      onUpdate(caseItem.id, { [field]: value})
    }
  }

  return (
    <div className="mt-4 pt-4 border-t">
      <h3 className="text-lg font-semibold mb-3">Szczegóły sprawy</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
        <EditableField
          label="Tytuł"
          value={caseItem.title}
          onSave={(value) => handleSave('title', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Klient"
          value={caseItem.client_name}
          onSave={(value) => handleSave('client_name', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Sygnatura"
          value={caseItem.case_number}
          onSave={(value) => handleSave('case_number', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Status"
          value={caseItem.status}
          onSave={(value) => handleSave('status', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Typ sprawy"
          value={caseItem.case_type || ''}
          onSave={(value) => handleSave('case_type', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Sąd"
          value={caseItem.court_name || ''}
          onSave={(value) => handleSave('court_name', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Sygnatura sądowa"
          value={caseItem.court_case_number || ''}
          onSave={(value) => handleSave('court_case_number', value)}
          disabled={isUpdating}
        />
        <EditableField
          label="Sędzia"
          value={caseItem.judge_name || ''}
          onSave={(value) => handleSave('judge_name', value)}
          disabled={isUpdating}
        />
        <div className="md:col-span-2">
          <EditableField
            label="Opis"
            as="textarea"
            value={caseItem.description || ''}
            onSave={(value) => handleSave('description', value)}
            disabled={isUpdating}
          />
        </div>
      </div>
    </div>
  )
} 
