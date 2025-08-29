#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end processor for Polish Supreme-Court rulings (SN) using OpenAI SDK
-----------------------------------------------------------------------------
• Uses o3-mini for intelligent PDF parsing and structure extraction
• Leverages OpenAI SDK for metadata extraction and entity recognition
• Produces structured JSON output with enhanced accuracy
"""

from __future__ import annotations
import json, logging, os, base64, asyncio, uuid, sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import fitz  # type: ignore  # PyMuPDF

# Add parent directories to Python path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field
from datetime import datetime
import dateparser
from tqdm import tqdm

# OpenAI imports
from openai import OpenAI

# Import OpenAI service from the app
from app.core.ai_client_factory import get_ai_client, AIProvider
from app.services.openai_client import get_openai_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get OpenAI service instance
openai_service = get_openai_service()


# ---------- 1  Pydantic models for structured output ----------------------- #

class LegalEntity(BaseModel):
    text: str = Field(description="The entity text")
    label: str = Field(description="Entity type: LAW_REF, DOCKET, PERSON, ORG, DATE")
    start: int = Field(description="Start character position")
    end: int = Field(description="End character position")


class LegalEntities(BaseModel):
    entities: List[LegalEntity] = Field(description="List of legal entities")


class RulingMetadata(BaseModel):
    docket: Optional[str] = Field(description="Case docket number", default=None)
    date: Optional[str] = Field(description="Decision date in ISO format", default=None)
    panel: Optional[List[str]] = Field(description="List of judges", default=[])
    
class RulingParagraph(BaseModel):
    section: Literal["header", "legal_question", "reasoning", "disposition", "body"] = Field(description="Section type: header, legal_question, reasoning, disposition, body")
    para_no: int = Field(description="Paragraph number", default=0)
    text: str = Field(description="Paragraph text", default="")

class ParsedRuling(BaseModel):
    paragraphs: List[RulingParagraph] = Field(description="List of paragraphs", default=[])

class RulingParagraphEnriched(RulingParagraph):
    entities: List[LegalEntity] = Field(description="Named entities in the paragraph")
    
class Ruling(BaseModel):
    name: str = Field(description="Ruling name")
    meta: RulingMetadata = Field(default=RulingMetadata())
    paragraphs: List[RulingParagraphEnriched]


# ---------- 2  OpenAI service configuration --------------------------------- #
# OpenAI service is initialized globally and configured via the app's config system

def get_o3_client(stream: bool = True):
    """Initialize o3/o1 chat client with appropriate settings"""
    # Note: Using o3-mini as the model
    # This is a placeholder function since the original file expects this function
    return openai_service  # Return the OpenAI service instance


# ---------- Stub implementations for compatibility -------------------------- #

class PromptTemplate:
    """Stub implementation to replace LangChain PromptTemplate"""
    def __init__(self, input_variables=None, template=""):
        self.input_variables = input_variables or []
        self.template = template
    
    def format(self, **kwargs):
        return self.template.format(**kwargs)


class HumanMessage:
    """Stub implementation to replace LangChain HumanMessage"""
    def __init__(self, content):
        self.content = content

# ---------- 3  PDF parsing with o3 ------------------------------------------ #

extract_prompt_template = """Jesteś ekspertem w analizie polskich orzeczeń Sądu Najwyższego. Przeanalizuj poniższe orzeczenie i wyodrębnij informacje strukturalne.

Tekst orzeczenia:
{pdf_path}

---
Zadania do wykonania:
1. Podziel dokument na logiczne sekcje:
   - header: Nagłówek z nazwą sądu, datą, sygnaturą
   - legal_question: Przedstawione zagadnienie prawne
   - reasoning: Uzasadnienie prawne sądu
   - disposition: Sentencja/rozstrzygnięcie
   - body: Pozostała treść

2. Podziel na paragrafy zachowując kontekst prawny.

Zwróć uwagę na:
- Właściwe rozpoznanie sekcji dokumentu
- Zachowanie polskich znaków diakrytycznych

{format_instructions}
"""

async def extract_pdf_with_o3(pdf_path: Path, is_batch: bool = False) -> ParsedRuling | bytes:
    """Use o3 to intelligently parse PDF structure and content"""

    
    # Extract raw text from PDF first
    doc = fitz.open(pdf_path)
    full_text = ""
    page_texts = []
    
    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        page_texts.append(page_text)
        full_text += f"\n--- PAGE {page_num + 1} ---\n{page_text}\n"
    
    doc.close()

    if is_batch:
        # For batch processing, return JSONL format for OpenAI batch API
        schema = ParsedRuling.model_json_schema()
        req = {
            "custom_id": "extract_pdf_with_o3-" + pdf_path.name,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "o3-mini",
                "messages": [
                    {"role": "user", "content": extract_prompt_template.format(
                        pdf_path=full_text, 
                        format_instructions=f"Return data as JSON matching this schema: {schema}"
                    )},
                ],
                "response_format": {"type": "json_object"}
            }
        }
        jsonl_bytes = json.dumps(req, ensure_ascii=False).encode("utf-8")
        return jsonl_bytes
    
    # Use structured output parsing via OpenAI service
    try:
        messages = [
            {"role": "user", "content": extract_prompt_template.format(
                pdf_path=full_text,
                format_instructions="Please structure your response according to the ParsedRuling schema."
            )}
        ]
        
        parsed_ruling = await openai_service.async_parse_structured_output(
            model="o3-mini",
            messages=messages,
            response_format=ParsedRuling,
            max_tokens=100000,
        )
        
        # Cast to ensure proper return type
        if not isinstance(parsed_ruling, ParsedRuling):
            raise RuntimeError(f"Expected ParsedRuling but got {type(parsed_ruling)}")
        return parsed_ruling
        
    except Exception as e:
        logger.error(f"Failed to parse o3 response: {e}")
        # Fallback parsing - convert Ruling to ParsedRuling
        ruling = await fallback_parse(full_text)
        return ParsedRuling(paragraphs=[RulingParagraph(**p.model_dump()) for p in ruling.paragraphs])

# ---------- 4  Fallback parsing for error cases ----------------------------- #

async def fallback_parse(text: str) -> Ruling:
    """Simple fallback parser if o3 fails"""
    import re
    
    # Split into paragraphs by double newlines or page markers
    paragraphs = []
    current_para = []
    
    lines = text.split('\n')
    for line in lines:
        if line.strip() == '' or line.startswith('--- PAGE'):
            if current_para:
                paragraphs.append('\n'.join(current_para))
                current_para = []
        else:
            current_para.append(line)
    
    if current_para:
        paragraphs.append('\n'.join(current_para))
    
    # Filter out empty paragraphs
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    # Basic metadata extraction
    metadata = RulingMetadata(
        docket=None,
        date=None,
        panel=[]
    )
    
    # Try to find docket number
    docket_patterns = [
        r'\(SYGN\. AKT ([^)]+)\)',
        r'Sygn\. akt\s+([IVX]+\s+[A-Z]+\s+\d+/\d+)',
        r'([IVX]+\s+[A-Z]+\s+\d+/\d+)'
    ]
    
    for pattern in docket_patterns:
        docket_match = re.search(pattern, text, re.IGNORECASE)
        if docket_match:
            metadata.docket = docket_match.group(1).strip()
            break
    
    # Try to find date
    date_match = re.search(r'Dnia\s+(.+?)(?=\s+roku)', text, re.IGNORECASE)
    if date_match:
        parsed_date = dateparser.parse(date_match.group(1), languages=['pl'])
        if parsed_date:
            metadata.date = parsed_date.date().isoformat()
    
    # Try to find judges
    judges_match = re.findall(r'Sędziowie?\s+SN[:\s]+([^,\n]+(?:,\s*[^,\n]+)*)', text)
    if judges_match:
        metadata.panel = [j.strip() for j in judges_match[0].split(',')]
    
    # Create paragraph objects
    ruling_paragraphs = []
    for idx, para in enumerate(paragraphs, 1):
        # Simple section detection
        section = "body"
        if idx == 1:
            section = "header"
        elif "zagadnienie prawne" in para.lower():
            section = "legal_question"
        elif "sąd najwyższy zważył" in para.lower() or "uzasadnienie" in para.lower():
            section = "reasoning"
        elif "postanawia" in para.lower() or "uchwala" in para.lower():
            section = "disposition"
        
        ruling_paragraphs.append(RulingParagraphEnriched(
            section=section,
            para_no=idx,
            text=para,
            entities=[]
        ))
    
    return Ruling(name="fallback_ruling", meta=metadata, paragraphs=ruling_paragraphs)

# ---------- 5  Enhanced entity extraction with o3 --------------------------- #

async def enhance_entities_with_o3(ruling: ParsedRuling, index: int, is_batch: bool = False) -> Ruling | List[bytes]:
    """Use o3-mini to enhance entity recognition in paragraphs"""
    
    entity_prompt = """Wyodrębnij encje prawne z poniższego polskiego tekstu prawnego.

Tekst: {text}

Zidentyfikuj i wyodrębnij:
1. LAW_REF: Odniesienia do przepisów prawnych (np. "art. 445 § 1 k.c.", "art. 118 KC", "ustawa z dnia...")
2. DOCKET: Sygnatury akt (np. "III CZP 123/05", "II CSK 456/20")
3. PERSON: Imiona i nazwiska osób (sędziowie, strony postępowania)
4. ORG: Organizacje, instytucje, firmy
5. DATE: Daty i wyrażenia czasowe

Dla każdej encji zwróć:
- text: dokładny tekst encji
- label: typ encji (LAW_REF, DOCKET, PERSON, ORG, DATE)
- start: pozycja początkowa znaku w tekście (licząc od 0)
- end: pozycja końcowa znaku w tekście

Uwaga: Odpowiedz w formacie JSON zgodnym ze schematem LegalEntities.
"""

    if is_batch:
        # For batch processing
        schema = LegalEntities.model_json_schema()
        jsonl_bytes = []
        for i in range(len(ruling.paragraphs)):
            req = {
                "custom_id": "extract_entities-" + str(index) + "-" + str(i),
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "o3-mini",
                    "messages": [
                        {"role": "user", "content": entity_prompt.format(text=ruling.paragraphs[i].text)},
                    ],
                    "response_format": {"type": "json_object"}
                }
            }
            j = json.dumps(req, ensure_ascii=False).encode("utf-8")
            jsonl_bytes.append(j)
        return jsonl_bytes
    else:
        # Process a single paragraph
        try:
            messages = [
                {"role": "user", "content": entity_prompt.format(text=ruling.paragraphs[index].text)}
            ]
            
            parsed_entities: LegalEntities = await openai_service.async_parse_structured_output(
                model="o3-mini",
                messages=messages,
                response_format=LegalEntities,
                max_tokens=20000,
            )
            
            # Create new ruling paragraph with entities
            enhanced_paragraph = RulingParagraphEnriched(
                **ruling.paragraphs[index].model_dump(),
                entities=parsed_entities.entities
            )
            
            # Update the ruling with enhanced paragraph
            enhanced_paragraphs = []
            for i, para in enumerate(ruling.paragraphs):
                if i == index:
                    enhanced_paragraphs.append(enhanced_paragraph)
                else:
                    enhanced_paragraphs.append(RulingParagraphEnriched(**para.model_dump(), entities=[]))
            
        except Exception as e:
            logger.warning(f"Failed to parse entities for paragraph {index}: {e}")
            # Use regex fallback
            entities = extract_entities_regex(ruling.paragraphs[index].text)
            enhanced_paragraphs = []
            for i, para in enumerate(ruling.paragraphs):
                if i == index:
                    enhanced_paragraphs.append(RulingParagraphEnriched(
                        **para.model_dump(),
                        entities=entities
                    ))
                else:
                    enhanced_paragraphs.append(RulingParagraphEnriched(**para.model_dump(), entities=[]))
    
    # Return Ruling with enhanced entities
    return Ruling(
        name=f"ruling-{index}",
        meta=RulingMetadata(),
        paragraphs=enhanced_paragraphs
    )

def extract_entities_regex(text: str) -> List[LegalEntity]:
    """Fallback regex-based entity extraction"""
    entities = []
    
    # LAW_REF patterns
    law_patterns = [
        (r'art\.\s*\d+[\w§\s]*(?:k\.c\.|KC|k\.p\.c\.|KPC)', 'LAW_REF'),
        (r'§\s*\d+[\w\s]*', 'LAW_REF'),
        (r'ustaw[aąy]\s+z\s+dnia\s+[\d\s\w]+', 'LAW_REF'),
    ]
    
    # DOCKET patterns
    docket_patterns = [
        (r'[IVX]+\s+[A-Z]+\s+\d+/\d+', 'DOCKET'),
    ]
    
    all_patterns = law_patterns + docket_patterns
    
    for pattern, label in all_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(LegalEntity(
                text=match.group(),
                label=label,
                start=match.start(),
                end=match.end()
            ))
    
    return entities

# ---------- 6  Document classification with o3 ------------------------------ #

def classify_sections_with_o3(ruling: ParsedRuling) -> ParsedRuling:
    """Use o3 to classify paragraph sections more accurately"""
    llm = get_o3_client()
    
    classification_prompt = PromptTemplate(
        input_variables=["paragraphs"],
        template="""Przeanalizuj poniższe paragrafy z orzeczenia Sądu Najwyższego i sklasyfikuj każdą sekcję.

Paragrafy:
{paragraphs}

Sklasyfikuj każdy numer paragrafu do jednej z sekcji:
- header: Nagłówek sprawy z nazwą sądu, datą, sygnaturą
- legal_question: Przedstawione zagadnienie prawne do rozstrzygnięcia
- reasoning: Uzasadnienie prawne sądu, analiza przepisów
- disposition: Sentencja, postanowienie sądu
- body: Pozostała treść ogólna

Zwróć obiekt JSON mapujący numery paragrafów na sekcje:
{{
  "1": "header",
  "2": "legal_question",
  "3": "reasoning",
  ...
}}

Wskazówki:
- Nagłówek zwykle zawiera "SĄD NAJWYŻSZY", datę i sygnaturę
- Zagadnienie prawne często zaczyna się od "przedstawił następujące zagadnienie"
- Uzasadnienie często zawiera "Sąd Najwyższy zważył, co następuje"
- Sentencja zawiera słowa "postanawia", "uchwala", "oddala"
"""
    )
    
    # Prepare paragraphs text with truncation for context
    para_texts = []
    for p in ruling.paragraphs:
        preview = p.text[:300] + "..." if len(p.text) > 300 else p.text
        para_texts.append(f"[Paragraf {p.para_no}]\n{preview}")
    
    messages = [HumanMessage(content=classification_prompt.format(
        paragraphs="\n\n".join(para_texts)
    ))]
    
    try:
        # Convert HumanMessage to OpenAI format  
        openai_messages = [{"role": "user", "content": messages[0].content}]
        response = llm.create_completion(
            model="gpt-4o-mini", 
            messages=openai_messages,
            max_tokens=4000,
            temperature=0.1
        )
        
        # Extract JSON from response
        content = response.choices[0].message.content.strip()  # type: ignore[attr-defined]
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
            
        classifications = json.loads(content)
        
        for para in ruling.paragraphs:
            if str(para.para_no) in classifications:
                para.section = classifications[str(para.para_no)]
                
    except Exception as e:
        logger.warning(f"Failed to parse section classifications: {e}")
        # Keep existing classifications
    
    return ruling

# ---------- 7  Main processing pipeline ------------------------------------- #

async def preprocess_sn_rulings(pdf_path: Path) -> List[Dict[str, Any]]:
    """Main pipeline using o3 for intelligent document processing"""
    logger.info(f"Processing {pdf_path} with o3-enhanced pipeline")
    
    try:
        # Step 1: Parse PDF with o3
        logger.info("Step 1: Parsing PDF structure with o3")
        parsed_ruling = await extract_pdf_with_o3(pdf_path)
        if isinstance(parsed_ruling, bytes):
            raise ValueError("Failed to parse PDF, received bytes instead of ParsedRuling")
        
        # Type assertion to help type checker understand parsed_ruling is not bytes here
        assert not isinstance(parsed_ruling, bytes), "parsed_ruling should not be bytes at this point"
        enriched_paragraphs = [RulingParagraphEnriched(**para.model_dump(), entities=[]) for para in parsed_ruling.paragraphs]
        ruling = Ruling(name="Supreme Court Ruling", meta=RulingMetadata(), paragraphs=enriched_paragraphs)

        # Step 2: Enhance entity extraction
        logger.info("Step 2: Enhancing entity recognition with o3")
        # Convert Ruling to ParsedRuling for the enhancement function
        # Convert Ruling to ParsedRuling for the enhancement function
        parsed_paragraphs = []
        for p in ruling.paragraphs:
            # Convert RulingParagraphEnriched back to RulingParagraph
            para_dict = p.model_dump(exclude={'entities'})
            parsed_paragraphs.append(RulingParagraph(**para_dict))
        parsed_for_enhancement = ParsedRuling(paragraphs=parsed_paragraphs)
        ruling = await enhance_entities_with_o3(parsed_for_enhancement, 0)
        
        # Step 3: Improve section classification
        # logger.info("Step 3: Classifying document sections with o3")
        # ruling = classify_sections_with_o3(ruling)
        
        # Convert to output format
        records = []
        
        for para in ruling.paragraphs:
            record = {
                "source_file": pdf_path.name,
                "section": para.section,
                "para_no": para.para_no,
                "text": para.text,
                "entities": [ent.model_dump() for ent in para.entities]
            }
            records.append(record)
        
        # Save to JSONL
        os.makedirs("data/jsonl", exist_ok=True)
        output_path = os.path.join("data/jsonl", pdf_path.stem + ".jsonl")
        
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        
        logger.info(f"Saved {len(records)} paragraphs to {output_path}")
        return records
        
    except Exception as e:
        logger.error(f"Error processing {pdf_path}: {e}", exc_info=True)
        raise

# ---------- 8  Batch processing with progress tracking ---------------------- #

async def process_batch(pdf_files: List[Path], extracted_jsonl: Optional[Path] = None, enriched_jsonl: Optional[Path] = None):
    """Process multiple PDFs with concurrent o3 calls"""
    all_jsonl_bytes = []
    failed_files = []
    cl = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    if not extracted_jsonl and not enriched_jsonl:
        for pdf_path in pdf_files:
            try:
                jsonl_bytes = await extract_pdf_with_o3(pdf_path, is_batch=True)
                all_jsonl_bytes.append(jsonl_bytes)
                logger.info(f"Successfully processed {pdf_path}")
                
            except Exception as e:
                logger.error(f"Failed to process {pdf_path}: {e}")
                failed_files.append(pdf_path)

        with open("data/jsonl/batch_input.jsonl", "w+b") as f:
            f.write(b"\n".join(all_jsonl_bytes))
            f.seek(0)
            file_ret = cl.files.create(
                file=f,
                purpose="batch",
            )
            logger.info(f"File created: {file_ret}")

        batch_ret = cl.batches.create(
            input_file_id=file_ret.id,
            endpoint="/v1/responses",
            completion_window="24h",
        )
        logger.info(f"Batch created: {batch_ret}")

    elif not enriched_jsonl:
        logger.info(f"Using extracted JSONL file: {extracted_jsonl}")
        all_records = []
        all_jsonl_bytes = []
        if extracted_jsonl is None:
            raise ValueError("extracted_jsonl path is required")
        with open(extracted_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_records.append(ParsedRuling.model_validate_json(line))
                else:
                    all_records.append(None)
        for i, record in enumerate(all_records):
            if record:
                all_jsonl_bytes.extend(await enhance_entities_with_o3(record, i, is_batch=True))
        with open("data/jsonl/batch_input_enriched.jsonl", "w+b") as f:
            f.write(b"\n".join(all_jsonl_bytes))
            f.seek(0)
            file_ret = cl.files.create(
                file=f,
                purpose="batch",
            )
            logger.info(f"File created: {file_ret}")
        batch_ret = cl.batches.create(
            input_file_id=file_ret.id,
            endpoint="/v1/responses",
            completion_window="24h",
        )
        logger.info(f"Batch created: {batch_ret}")

    else:
        parsed_rulings = []
        if extracted_jsonl is None:
            raise ValueError("extracted_jsonl path is required")
        with open(extracted_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    parsed_rulings.append(ParsedRuling.model_validate_json(line))
                else:
                    parsed_rulings.append(None)
        rulings: List[Optional[Ruling]] = []
        for parsed in parsed_rulings:
            if parsed:
                rulings.append(Ruling(meta=RulingMetadata(),
                                    paragraphs=[RulingParagraphEnriched(**para.model_dump(), entities=[])
                                                for para in parsed.paragraphs],
                                    name=uuid.uuid4().hex,  # TODO: use actual name 
                                )
                            )
            else:
                rulings.append(None)

                
        logger.info(f"Using enriched JSONL file: {enriched_jsonl}")
        all_records = []
        paragraphs = []
        with open(enriched_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_records.append(json.loads(line))
        
        for _, record in enumerate(all_records):
            for rule_num, paragraphs in record.items():
                for para_num, para in paragraphs.items():
                    try:
                        ruling = rulings[int(rule_num)]
                        if ruling:
                            p = next(filter(lambda p: p.para_no - 1 == int(para_num), ruling.paragraphs))
                            if p is not None:

                                p.entities = [LegalEntity(**e) for e in para["entities"]]
                        else:
                            logger.error(f"Ruling not found for rule {rule_num}")
                    except Exception as e:
                        logger.error(f"Error processing {para_num} in {rule_num}: {e}")
                        continue
        
        for ruling in rulings:
            docket = None
            date = None
            panel = []
            for para in [p for p in ruling.paragraphs if p.section == "header"] if ruling is not None else []:
                d = [e for e in para.entities if e.label == "DOCKET"]
                if d and not docket:
                    docket = d[0].text
                da = [e for e in para.entities if e.label == "DATE"]
                if da and not date:
                    date = da[0].text
                pe = [e for e in para.entities if e.label == "PERSON"]
                if pe:
                    for p in pe:
                        start = max(0, p.start - 10)
                        end = min(len(para.text), p.end + 1)
                        if "sędzia" in para.text[start:end].lower() or "sedzia" in para.text[start:end].lower() or "ssn" in para.text[start:end].lower():
                            panel.append(p.text)
            if ruling is not None:

                ruling.meta = RulingMetadata(docket=docket, date=date, panel=panel)

        with open("data/jsonl/final_sn_rulings.jsonl", "w") as f:
            for ruling in rulings:
                if ruling:
                    is_valid = ruling.meta.docket and (int(bool(ruling.meta.date)) + int(bool(ruling.meta.panel))) >= 1
                    if is_valid:
                        ruling.name = ruling.meta.docket or "Unknown Ruling"  # Provide fallback
                        f.write(ruling.model_dump_json() + "\n")




# ---------- 9  Utility functions -------------------------------------------- #

def validate_output(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate the output records for completeness"""
    required_fields = ["text", "para_no", "section"]
    valid_records = []
    invalid_records = []
    for record in records:
        if not record:
            invalid_records.append(record)
            continue
        for field in required_fields:
            if field not in record or not record[field]:
                logger.error(f"Missing required field '{field}' in record")
                invalid_records.append(record)
                continue
        valid_records.append(record)
    
    return valid_records, invalid_records

def merge_jsonl_files(output_dir: Path = Path("data/jsonl"), 
                     merged_file: Path = Path("data/sn_rulings_merged.jsonl")):
    """Merge all JSONL files into a single file"""
    all_records = []
    
    for jsonl_file in output_dir.glob("*.jsonl"):
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_records.append(json.loads(line))
    
    with open(merged_file, "w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    logger.info(f"Merged {len(all_records)} records into {merged_file}")
    return all_records


async def process_async(pdf_files: List[Path], max_workers: int = 3):
    sem = asyncio.Semaphore(max_workers)
    with tqdm(total=len(pdf_files), desc="Processing PDFs") as pbar:
        async def process_file(pdf_path: Path):
            async with sem:
                try:
                    records = await preprocess_sn_rulings(pdf_path)
                    pbar.update(1)
                    return records
                except Exception as e:
                    logger.error(f"Error processing {pdf_path}: {e}")
                    pbar.update(1)
                    return None

        return await asyncio.gather(*[process_file(pdf_path) for pdf_path in pdf_files])

# ---------- 10 Main entry point --------------------------------------------- #

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Process Polish Supreme Court rulings with o3/o1 enhanced pipeline"
    )
    parser.add_argument(
        "--input-dir", 
        type=Path, 
        default=Path("data/pdfs/sn-rulings"),
        help="Directory containing PDF files"
    )
    parser.add_argument(
        "--workers", 
        type=int, 
        default=3,
        help="Number of concurrent workers for o3 calls"
    )
    parser.add_argument(
        "--single-file", 
        type=Path,
        help="Process a single PDF file"
    )
    parser.add_argument(
        "--run-async", 
        action="store_true",
        help="Process asynchronously"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge all JSONL outputs into a single file"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate output after processing"
    )
    parser.add_argument(
        "--extracted-jsonl",
        type=Path,
        help="Path to the JSONL file containing the extracted paragraphs"
    )
    parser.add_argument(
        "--enriched-jsonl",
        type=Path,
        help="Path to the JSONL file containing the enriched paragraphs"
    )
    
    args = parser.parse_args()
    
    if args.single_file:
        # Process single file
        records = await preprocess_sn_rulings(args.single_file)
        if args.validate:
            valid_records, invalid_records = validate_output(records)
            logger.info(f"Valid records: {len(valid_records)}")
            logger.info(f"Invalid records: {len(invalid_records)}")

    elif args.run_async:
        # Process all PDFs in directory asynchronously
        dir_path: Path = args.input_dir
        pdf_files = list(dir_path.glob("*.pdf"))
        pdf_files = [p for p in pdf_files if p.is_file() and not p.name.endswith("123_05.pdf")]
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        if pdf_files:
            records = await process_async(pdf_files, max_workers=args.workers)
            logger.info(f"Processed {len(records)} PDF files")
            if args.validate:
                # Flatten the list of records, filtering out None values
                flattened_records = [
                    record for record_list in records 
                    if record_list is not None 
                    for record in record_list
                ]
                valid_records, invalid_records = validate_output(flattened_records)
                logger.info(f"Valid records: {len(valid_records)}")
                logger.info(f"Invalid records: {len(invalid_records)}")
            if args.merge:
                merge_jsonl_files()
                
    elif args.merge:
        # Just merge existing files
        merge_jsonl_files()
        
    else:
        # Process all PDFs in directory
        pdf_files = list(args.input_dir.glob("*-ocrd.pdf"))
        pdf_files = [p for p in pdf_files if p.is_file() and not p.name.endswith("123_05.pdf")]
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        if pdf_files:
            await process_batch(pdf_files, args.extracted_jsonl, args.enriched_jsonl)
        else:
            logger.warning(f"No PDF files found in {args.input_dir}")

if __name__ == "__main__":
    asyncio.run(main())
