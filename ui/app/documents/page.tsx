'use client';

import React, { useState } from 'react';
import DocumentGenerationView from '@/components/DocumentGenerationView';
import { Document } from '@/lib/types';
import { api } from '@/lib/api/client';

const mockTemplates = [
  { id: 'pozew_o_zaplate', name: 'Pozew o zapłatę', description: 'Standardowy pozew o zapłatę w postępowaniu upominawczym.' },
  { id: 'wezwanie_do_zaplaty', name: 'Wezwanie do zapłaty', description: 'Przedsądowe wezwanie do uregulowania należności.' },
  { id: 'odpowiedz_na_pozew', name: 'Odpowiedź na pozew', description: 'Odpowiedź na pozew w sprawie cywilnej.' },
];

const DocumentsPage = () => {
  const [generatedDocuments, setGeneratedDocuments] = useState<Document[]>([]);

  const handleGenerateDocument = async (templateId: string, context: Record<string, any>): Promise<Document | null> => {
    try {
      // Replace with your actual API call
      console.log('Generating document with:', { templateId, context });
      const newDocument = await api.documents.create({
        document_type: templateId,
        title: `Nowy dokument - ${new Date().toISOString()}`,
        status: 'draft',
        content: JSON.stringify(context),
        case_id: 'case-123', // This should be dynamic
      });
      if (newDocument) {
        setGeneratedDocuments(prev => [...prev, newDocument]);
        return newDocument;
      }
      return null;
    } catch (error) {
      console.error('Failed to generate document:', error);
      throw error;
    }
  };

  return (
    <div className="container mx-auto p-4 md:p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Centrum Dokumentów</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div>
          <DocumentGenerationView templates={mockTemplates} onGenerate={handleGenerateDocument} />
        </div>
        
        <div className="bg-white p-4 rounded-lg shadow-md">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Ostatnio wygenerowane</h3>
          {generatedDocuments.length === 0 ? (
            <p className="text-gray-500">Nie wygenerowano jeszcze żadnych dokumentów.</p>
          ) : (
            <ul className="space-y-3">
              {generatedDocuments.map((doc) => (
                <li key={doc.id} className="p-3 bg-gray-50 border rounded-md">
                  <a
                    href={`/documents/${doc.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-blue-600 hover:underline"
                  >
                    📄 {doc.title}
                  </a>
                  <p className="text-sm text-gray-600 mt-1">Status: {doc.status}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};

export default DocumentsPage;
