# Polish Legal Document Hierarchy Fix

## Problem
The original chunking implementation incorrectly treated chapters (Rozdział) as smaller units than articles, when in fact the Polish legal document hierarchy follows this structure:

### Correct Hierarchy (from highest to lowest):
1. **Część** (Part) - e.g., "CZĘŚĆ OGÓLNA" (General Part), "CZĘŚĆ SZCZEGÓLNA" (Special Part)
2. **Dział** (Division) - e.g., "DZIAŁ I: PRZEPISY WSTĘPNE"
3. **Rozdział** (Chapter) - e.g., "Rozdział I: Osoby fizyczne"
4. **Artykuł** (Article) - e.g., "Art. 415."

### Alternative/Additional Structures:
- **Księga** (Book) - Used in some codes between Part and Division
- **Tytuł** (Title) - Alternative to Division in some codes

## Solution

Created `pdf2chunks_fixed.py` with corrected hierarchy parsing that:

1. **Properly orders structural elements** from highest (Część) to lowest (Artykuł)
2. **Tracks hierarchy context** as the parser moves through the document
3. **Stores full hierarchy metadata** for each article chunk
4. **Builds section paths** showing the complete hierarchy (e.g., "Część OGÓLNA > Dział I > Rozdział II")

## Key Changes

### 1. Updated Regex Patterns
```python
PATTERNS = {
    'part': re.compile(r'^CZĘŚĆ\s+(\w+)', re.MULTILINE),
    'division': re.compile(r'^DZIAŁ\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
    'chapter': re.compile(r'^Rozdział\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
    'book': re.compile(r'^KSIĘGA\s+(\w+)', re.MULTILINE),
    'title': re.compile(r'^TYTUŁ\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
}
```

### 2. Enhanced Metadata Storage
Each chunk now includes:
```python
{
    "hierarchy": {
        "part": "OGÓLNA",
        "part_name": "Przepisy ogólne",
        "division": "I",
        "division_name": "PRZEPISY WSTĘPNE",
        "chapter": "II",
        "chapter_name": "Osoby fizyczne",
        "book": None,
        "title": None
    }
}
```

### 3. Section Path Building
Articles now include their full hierarchical path:
- Before: Just "Rozdział I"
- After: "Część OGÓLNA > Dział I: PRZEPISY WSTĘPNE > Rozdział I: Osoby fizyczne"

## Usage

### To test the new parser:
```bash
python ingest/test_hierarchy.py
```

### To compare old vs new parser:
```bash
python ingest/fix_hierarchy.py
```

### To update existing chunks in database:
```bash
python ingest/fix_hierarchy.py
# Then answer 'y' when prompted
```

## Benefits

1. **Better search results** - Users can now search within specific parts, divisions, or chapters
2. **Improved context** - Each article chunk knows its exact position in the legal hierarchy
3. **Accurate citations** - The system can provide full hierarchical citations
4. **Enhanced navigation** - Can build document tree structures for browsing

## Example Output

```
Article: 8§1
Section Path: Część OGÓLNA > Dział II: OSOBY > Rozdział I: Osoby fizyczne
Hierarchy Details:
  - Part: OGÓLNA
  - Division: II
  - Chapter: I
Content: Każdy człowiek od chwili urodzenia ma zdolność prawną.
```

## Migration

For existing deployments:
1. Run `fix_hierarchy.py` to update metadata in existing chunks
2. Re-ingest documents using the new parser for best results
3. Update search queries to leverage the new hierarchy fields