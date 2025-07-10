'use client'

import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from '@/lib/api/client'
import type { Case, Document } from '@/lib/types'

const DocumentsView = () => {
  const [stagedFiles, setStagedFiles] = useState<File[]>([])
  const [cases, setCases] = useState<Case[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedCase, setSelectedCase] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        const [casesData, documentsData] = await Promise.all([
          api.cases.list(),
          api.documents.list()
        ])
        setCases(casesData)
        setDocuments(documentsData)
      } catch (err) {
        console.error('Failed to fetch data', err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setStagedFiles(prev => [...prev, ...acceptedFiles])
  }, [])

  const { getRootProps, getInputProps, open } = useDropzone({ onDrop, noClick: true })

  const handleUpload = async () => {
    if (!selectedCase || stagedFiles.length === 0) return

    try {
      await Promise.all(
        stagedFiles.map(file => api.documents.upload(selectedCase, file))
      )
      setStagedFiles([])
      // Refresh documents list
      const documentsData = await api.documents.list()
      setDocuments(documentsData)
    } catch (error) {
      console.error('Failed to upload documents', error)
    }
  }

  const getCaseName = (caseId: string) => {
    const foundCase = cases.find(c => c.id === caseId)
    return foundCase?.reference_number || 'Unknown case'
  }

  return (
    <div {...getRootProps()} className="p-4">
      <input {...getInputProps()} />
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Documents</h1>
        <button onClick={open} className="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600">
          Dodaj dokumenty
        </button>
      </div>

      {/* Documents list */}
      <div className="mb-8">
        {loading ? (
          <div className="text-center py-8 text-gray-500">Loading documents...</div>
        ) : documents.length === 0 ? (
          <div className="text-center py-8 text-gray-500">No documents uploaded yet.</div>
        ) : (
          <div className="grid gap-4">
            {documents.map((doc) => (
              <div key={doc.id} className="border rounded-lg p-4 hover:shadow-md transition-shadow bg-white">
                <div className="flex justify-between items-start">
                  <div>
                    <h3 className="font-semibold text-lg">{doc.title}</h3>
                    <p className="text-sm text-gray-600">
                      Case: {getCaseName(doc.case_id)} • Type: {doc.document_type} • Status: {doc.status}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      Created: {new Date(doc.created_at).toLocaleDateString()}
                      {doc.filed_date && ` • Filed: ${new Date(doc.filed_date).toLocaleDateString()}`}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button className="text-blue-600 hover:text-blue-800 text-sm">View</button>
                    <button className="text-red-600 hover:text-red-800 text-sm">Delete</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Staging area */}
      {stagedFiles.length > 0 && (
        <div className="p-4 border-2 border-dashed rounded-lg bg-gray-50">
          <h2 className="text-xl font-semibold mb-4">Staged Documents</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-4">
            {stagedFiles.map((file, i) => (
              <div key={i} className="p-3 border rounded-md shadow-sm bg-white">
                <p className="font-medium text-sm truncate">{file.name}</p>
                <p className="text-xs text-gray-500">{(file.size / 1024).toFixed(1)} KB</p>
                <button 
                  onClick={() => setStagedFiles(prev => prev.filter((_, idx) => idx !== i))}
                  className="text-red-600 hover:text-red-800 text-xs mt-1"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <select 
              onChange={(e) => setSelectedCase(e.target.value)} 
              className="p-2 border rounded-md bg-white text-gray-900"
              defaultValue=""
            >
              <option value="" disabled className="text-gray-500">Wybierz sprawę</option>
              {cases.map(c => (
                <option key={c.id} value={c.id} className="text-gray-900">{c.reference_number}</option>
              ))}
            </select>
            <button 
              onClick={handleUpload} 
              disabled={!selectedCase}
              className="px-4 py-2 bg-green-500 text-white rounded-md disabled:bg-gray-300 hover:bg-green-600"
            >
              Dodaj do sprawy
            </button>
            <button 
              onClick={() => setStagedFiles([])} 
              className="px-4 py-2 bg-gray-500 text-white rounded-md hover:bg-gray-600"
            >
              Clear All
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default DocumentsView
