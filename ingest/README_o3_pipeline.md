# Polish Supreme Court Rulings Preprocessing with O3/O1

This refactored pipeline uses OpenAI's O3/O1 models through LangChain for intelligent document processing of Polish Supreme Court (Sąd Najwyższy) rulings.

## Key Improvements

### 1. **Intelligent PDF Parsing**
- Uses O3/O1 to understand document structure instead of manual heuristics
- Automatically identifies logical sections (header, legal question, reasoning, disposition)
- Preserves legal context when splitting into paragraphs

### 2. **Enhanced Metadata Extraction**
- LLM-based extraction of court metadata
- Accurate date parsing with Polish language support
- Proper identification of judges panel

### 3. **Advanced Entity Recognition**
- Uses O3/O1 for context-aware entity extraction
- Recognizes complex legal references (e.g., "art. 445 § 1 k.c.")
- Accurate character position tracking
- Supports entity types: LAW_REF, DOCKET, PERSON, ORG, DATE

### 4. **Structured Output**
- Pydantic models ensure consistent data structure
- JSON Lines format for easy downstream processing
- Full metadata preserved with each paragraph

## Usage

### Single File Processing
```bash
python ingest/preprocess_sn_o3.py --single-file data/pdfs/sn-rulings/example.pdf
```

### Batch Processing
```bash
python ingest/preprocess_sn_o3.py --input-dir data/pdfs/sn-rulings --workers 3
```

### Merge Output Files
```bash
python ingest/preprocess_sn_o3.py --merge
```

### With Validation
```bash
python ingest/preprocess_sn_o3.py --input-dir data/pdfs/sn-rulings --validate
```

## Output Format

Each paragraph is saved as a JSON line with the following structure:

```json
{
  "court": "Sąd Najwyższy",
  "docket": "III CZP 45/23",
  "date": "2023-06-15",
  "panel": ["Jan Kowalski", "Anna Nowak"],
  "source_file": "orzeczenie_123.pdf",
  "section": "reasoning",
  "para_no": 5,
  "text": "Sąd Najwyższy zważył, co następuje...",
  "entities": [
    {
      "text": "art. 445 § 1 k.c.",
      "label": "LAW_REF",
      "start": 45,
      "end": 62
    }
  ]
}
```

## Architecture

```
PDF Document
    ↓
Extract Raw Text (PyMuPDF)
    ↓
Parse Structure with O3/O1
    ├── Extract Metadata
    ├── Identify Sections
    └── Split Paragraphs
    ↓
Enhance Entities with O3/O1
    ↓
Classify Sections with O3/O1
    ↓
Output JSON Lines
```

## Configuration

The pipeline uses the following environment variables (via settings):

- `OPENAI_API_KEY`: Required for O3/O1 access
- Model selection: Currently uses "o1-preview" (update when o3 is available)

## Error Handling

- Fallback parser for cases where O3/O1 fails
- Regex-based entity extraction as backup
- Comprehensive logging for debugging
- Graceful handling of malformed PDFs

## Performance Considerations

- Concurrent processing with configurable workers
- Batch processing of paragraphs for entity extraction
- Progress tracking with tqdm
- Typical processing: ~30-60 seconds per document

## Dependencies

- `langchain-openai`: O3/O1 integration
- `PyMuPDF`: PDF text extraction
- `pydantic`: Structured data models
- `dateparser`: Polish date parsing
- `tqdm`: Progress bars

## Testing

Run the test script:
```bash
python ingest/test_preprocess_o3.py
```

## Migration from Old Pipeline

The new pipeline produces compatible output with these enhancements:
- More accurate section classification
- Better entity recognition
- Consistent metadata extraction
- Added `source_file` field for traceability

Existing downstream processes should work without modification.