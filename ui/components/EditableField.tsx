'use client'

import { useState, useRef, useEffect } from 'react'

interface EditableFieldProps {
  value: string
  onSave: (value: string) => void
  label: string
  as?: 'input' | 'textarea'
  disabled?: boolean
}

export default function EditableField({ value, onSave, label, as = 'input', disabled = false }: EditableFieldProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [currentValue, setCurrentValue] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (isEditing) {
      if (as === 'input' && inputRef.current) {
        inputRef.current.focus()
      } else if (as === 'textarea' && textareaRef.current) {
        textareaRef.current.focus()
      }
    }
  }, [isEditing, as])

  const handleSave = () => {
    console.log('Handler: handleSave in EditableField', { label, currentValue });
    if (currentValue !== value) {
      onSave(currentValue)
    }
    setIsEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    console.log('Handler: handleKeyDown in EditableField', { key: e.key, label });
    if (e.key === 'Enter' && !e.shiftKey && as === 'textarea') {
      e.preventDefault()
      handleSave()
    } else if (e.key === 'Enter' && as === 'input') {
      handleSave()
    } else if (e.key === 'Escape') {
      setCurrentValue(value)
      setIsEditing(false)
    }
  }

  return (
    <div className="mb-2 relative">
      <strong className="text-sm text-gray-800">{label}:</strong>
      {isEditing && !disabled ? (
        as === 'textarea' ? (
          <textarea
            ref={textareaRef}
            value={currentValue}
            onChange={(e) => setCurrentValue(e.target.value)}
            onBlur={handleSave}
            onKeyDown={handleKeyDown}
            className="mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            rows={4}
            disabled={disabled}
          />
        ) : (
          <input
            ref={inputRef}
            type="text"
            value={currentValue}
            onChange={(e) => setCurrentValue(e.target.value)}
            onBlur={handleSave}
            onKeyDown={handleKeyDown}
            className="mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            disabled={disabled}
          />
        )
      ) : (
        <div className={`mt-1 p-2 rounded-md relative ${disabled ? 'bg-gray-100 opacity-50' : 'hover:bg-gray-100 cursor-pointer'}`}>
          <p
            className="text-gray-600 text-sm break-words whitespace-pre-wrap prose prose-sm"
            onClick={() => {
              console.log('Handler: onClick to edit field', { label, disabled });
              !disabled && setIsEditing(true)
            }}
          >
            {value || <span className="text-gray-400">Brak</span>}
          </p>
          {disabled && isEditing && (
            <div className="absolute inset-0 flex items-center justify-center">
              <svg className="animate-spin h-5 w-5 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </div>
          )}
        </div>
      )}
    </div>
  )
} 
