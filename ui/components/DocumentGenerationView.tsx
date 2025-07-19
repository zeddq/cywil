import React, { useState } from 'react';
import { FilePlus, Send, Loader2 } from 'lucide-react';
import { Document } from '@/lib/types';

interface DocumentGenerationViewProps {
  templates: { id: string; name: string; description: string }[];
  onGenerate: (templateId: string, context: Record<string, any>) => Promise<Document | null>;
}

const DocumentGenerationView: React.FC<DocumentGenerationViewProps> = ({ templates, onGenerate }) => {
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [caseFacts, setCaseFacts] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [generatedDocument, setGeneratedDocument] = useState<Document | null>(null);

  const handleGenerateClick = async () => {
    if (!selectedTemplate || !caseFacts.trim()) {
      alert('Proszę wybrać szablon i podać fakty sprawy.');
      return;
    }
    setIsLoading(true);
    setGeneratedDocument(null);
    try {
      const doc = await onGenerate(selectedTemplate, { facts: caseFacts });
      setGeneratedDocument(doc);
    } catch (error) {
      console.error('Błąd generowania dokumentu:', error);
      alert('Wystąpił błąd podczas generowania dokumentu.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white p-4 rounded-lg shadow-md mt-4">
      <div className="flex items-center mb-4">
        <FilePlus className="w-6 h-6 text-primary mr-2" />
        <h3 className="text-lg font-semibold text-gray-800">Generowanie dokumentu</h3>
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="template-select" className="block text-sm font-medium text-gray-700 mb-1">
            Wybierz szablon
          </label>
          <select
            id="template-select"
            value={selectedTemplate ?? ''}
            onChange={(e) => setSelectedTemplate(e.target.value)}
            className="w-full p-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
          >
            <option value="" disabled>Wybierz...</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name} - {template.description}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="case-facts" className="block text-sm font-medium text-gray-700 mb-1">
            Podaj kluczowe fakty sprawy
          </label>
          <textarea
            id="case-facts"
            rows={5}
            value={caseFacts}
            onChange={(e) => setCaseFacts(e.target.value)}
            className="w-full p-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
            placeholder="Np. Klient Jan Kowalski zawarł umowę z firmą XYZ w dniu 1.01.2024..."
          />
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleGenerateClick}
            disabled={isLoading || !selectedTemplate}
            className="flex items-center px-4 py-2 bg-primary text-white rounded-md hover:bg-primary-dark disabled:bg-gray-400"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                <span>Generowanie...</span>
              </>
            ) : (
              <>
                <Send className="w-5 h-5 mr-2" />
                <span>Generuj dokument</span>
              </>
            )}
          </button>
        </div>
      </div>

      {generatedDocument && (
        <div className="mt-6 p-4 border-t">
          <h4 className="text-md font-semibold mb-2">Wygenerowany dokument:</h4>
          <div className="p-3 bg-gray-50 border rounded-md">
            <a
              href={`/documents/${generatedDocument.id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              📄 {generatedDocument.title}
            </a>
            <p className="text-sm text-gray-600 mt-1">Status: {generatedDocument.status}</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default DocumentGenerationView; 
