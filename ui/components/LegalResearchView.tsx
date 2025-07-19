import React from 'react';
import { FileText, PlusCircle, Star, ThumbsDown, ThumbsUp } from 'lucide-react';
import { Citation } from '@/lib/types';

interface LegalResearchViewProps {
  citations: Citation[];
  onAddToCase: (citation: Citation) => void;
  onRate: (citation: Citation, rating: 'good' | 'bad') => void;
}

const LegalResearchView: React.FC<LegalResearchViewProps> = ({ citations, onAddToCase, onRate }) => {
  if (citations.length === 0) {
    return null;
  }

  return (
    <div className="bg-white p-4 rounded-lg shadow-md mt-4">
      <div className="flex items-center mb-3">
        <FileText className="w-6 h-6 text-primary mr-2" />
        <h3 className="text-lg font-semibold text-gray-800">Wyniki wyszukiwania</h3>
      </div>
      <div className="space-y-3">
        {citations.map((citation, index) => (
          <div key={index} className="border p-3 rounded-md bg-gray-50 hover:bg-gray-100 transition-colors">
            <div className="flex justify-between items-start">
              <div>
                <p className="font-semibold text-primary">{citation.article} {citation.source}</p>
                <p className="text-sm text-gray-700 mt-1">{citation.text}</p>
              </div>
              <div className="flex items-center space-x-2 ml-4">
                <button
                  onClick={() => onAddToCase(citation)}
                  title="Dodaj do sprawy"
                  className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-100 rounded-full transition-colors"
                >
                  <PlusCircle className="w-5 h-5" />
                </button>
                {citation.score && (
                  <div className="flex items-center text-xs text-gray-500">
                    <Star className="w-4 h-4 text-yellow-500 mr-1" />
                    <span>{citation.score.toFixed(2)}</span>
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-end items-center mt-2 space-x-2">
              <button
                onClick={() => onRate(citation, 'good')}
                title="Dobre trafienie"
                className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-100 rounded-full transition-colors"
              >
                <ThumbsUp className="w-4 h-4" />
              </button>
              <button
                onClick={() => onRate(citation, 'bad')}
                title="Złe trafienie"
                className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-100 rounded-full transition-colors"
              >
                <ThumbsDown className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default LegalResearchView; 
