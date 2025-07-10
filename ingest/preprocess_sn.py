"""
This script is used to preprocess the Polish Supreme Court (Sąd Najwyższy) rulings.

The data is stored in the data/sn_rulings directory.

The data is in the following format:
- data/pdfs/sn-rulings/*.pdf


The data is in the following format:
- data/pdfs/sn-rulings/*.pdf

The script will:
- convert the pdfs to text
- split the text into chunks
- save the chunks to the data/chunks/sn-rulings directory

"""
from __future__ import annotations
import argparse, json, re, unicodedata, datetime, logging, os
from pathlib import Path
from typing import Dict, List, Any, Iterable, Tuple

import fitz                                    # PyMuPDF
import spacy
from spacy.pipeline import EntityRuler
import dateparser
import statistics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end processor for Polish Supreme-Court rulings (SN)
---------------------------------------------------------
• Extracts text from PDF (born-digital or OCR’d)
• Cleans & de-hyphenates lines
• Pulls key metadata via regex
• Runs spaCy-pl (`pl_core_news_lg`) + rule NER for LAW_REF / DOCKET
• Splits body into paragraphs, emits one JSON row per paragraph
"""


# ---------- 1  spaCy pipeline with legal tweaks ---------------------------- #

def build_nlp() -> spacy.language.Language:
    nlp = spacy.load("pl_core_news_lg")
    ruler = nlp.add_pipe("entity_ruler", before="ner")
    ruler.add_patterns([
        # art. 445 § 1 k.c.
        {"label": "LAW_REF",
         "pattern": [
             {"TEXT": {"REGEX": r"^(art\.|§)$"}},
             {"IS_DIGIT": True, "OP": "+"},
             {"TEXT": {"REGEX": r"^[a-zA-ZłŁ\.]+$"}, "OP": "*"},
         ]},
        # III CZP 123/05
        {"label": "DOCKET",
         "pattern": [
             {"TEXT": {"REGEX": r"^[IVXLCDM]+$"}},
             {"TEXT": "CZP"},
             {"SHAPE": "d/d"},
         ]},
    ])
    return nlp

def extract_paragraphs(doc: fitz.Document) -> Iterable[str]:
    lines = []
    candidates = []
    carry = False
    for page in doc:
        raw_lines = page.get_text("dict")["blocks"]
        # Flatten to list[(y_top, y_bottom, text)]
        for b in raw_lines:
            span_lines = b.get("lines", [])
            text = "".join(span["text"] for s in span_lines for span in s["spans"])
            if len(span_lines) == 1 or text.isupper():
                carry = False
                lines.append((b["bbox"][1], b["bbox"][3], text))
                continue
            elif len(lines) > 0 and not carry:
                candidates.append(lines)
                lines = []
            if len(span_lines) == 0:
                continue
            y0 = min(s["bbox"][1] for s in span_lines[0]["spans"])
            y1 = max(s["bbox"][3] for s in span_lines[0]["spans"])
            if text:
                lines.append((y0, y1, text))
            candidates.append(lines)
            carry = False
            lines = []
            
        for candidate in candidates[:-1]:
            candidate.sort(key=lambda x: x[0])            # top-to-bottom
            yield "\n".join(x[2] for x in candidate)
        
        if len(candidates) > 0:
            candidate = candidates[-1]
            if len(candidate) > 0 and candidate[-1][2].strip().endswith("."):
                candidate.sort(key=lambda x: x[0])            # top-to-bottom
                yield "\n".join(x[2] for x in candidate)
                carry = False
            else:
                lines = candidate
                carry = True
        candidates = []
        
        # # Compute baseline line-height
        # heights = [y1 - y0 for y0, y1, _ in candidate]
        # line_height = statistics.median(heights)
        # threshold   = 1.5 * line_height           # tune as needed

        # para, last_bottom = [], None
        # for y0, y1, txt in lines:
        #     if last_bottom is not None and (y0 - last_bottom) > threshold:
        #         yield " ".join(para)              # emit paragraph
        #         para = []
        #     para.append(txt)
        #     last_bottom = y1
        # if para:
        #     yield " ".join(para)

# ---------- 2  PDF → raw text --------------------------------------------- #

def extract_text(pdf_path: Path) -> Tuple[str, Iterable[str]]:
    doc = fitz.open(pdf_path)
    paragraphs = list(extract_paragraphs(doc))
    joined = " ".join(paragraphs)
    doc.close()
    return joined, paragraphs


# ---------- 3  Clean & normalise ------------------------------------------ #

def clean_text(joined: Iterable[str]) -> Iterable[str]:
    cleaned = []
    for j in joined:
        # de-hyphenate at line breaks
        j = re.sub(r"(\w+)-\n(\w+)", r"\1\2", j)

        # collapse line-breaks inside sentences
        j = re.sub(r"(?<![.\n])\n(?!\n)", " ", j)

        # strip multiple blank lines
        j = re.sub(r"\n{3,}", "\n\n", j)
        cleaned.append(unicodedata.normalize("NFC", j.strip()))

    return cleaned


# ---------- 4  Metadata harvest ------------------------------------------ #

META_PATTERNS = {
    "court": re.compile(r"^POSTANOWIENIE SĄDU NAJWYŻSZEGO", re.M),
    "docket": re.compile(r"\(SYGN\. AKT ([^)]+)\)"),
    "date": re.compile(r"Dnia\s+(.+?)(?=\s+ROKU?)", re.IGNORECASE),
}


def extract_meta(text: str) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for k, rx in META_PATTERNS.items():
        m = rx.search(text)
        if m:
            meta[k] = m.group(1 if k != "court" else 0).strip()

    if "date" in meta:
        parsed = dateparser.parse(meta["date"], languages=["pl"])
        if parsed:
            meta["date"] = parsed.date().isoformat()
        else:
            meta["date"] = meta["date"]

    # Judges panel (rough heuristic)
    judges = re.findall(r"Sędziowie? SN:[^\n]+", text)
    if judges:
        meta["panel"] = "; ".join(judges)

    return meta


# ---------- 5  Paragraph-level enrichment --------------------------------- #

def enrich_paragraphs(paragraphs: Iterable[str], meta: Dict[str, Any], NLP: spacy.language.Language) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, para in enumerate(paragraphs, 1):
        doc = NLP(para)
        ents = [
            {"text": e.text, "label": e.label_, "start": e.start_char, "end": e.end_char}
            for e in doc.ents
        ]
        out.append({
            **meta,
            "section": locate_section(idx, para),
            "para_no": idx,
            "text": para,
            "entities": ents,
        })
    return out


def locate_section(idx: int, para: str) -> str:
    """
    Tiny heuristic: first para after quote block = legal_question,
    first 'Sąd Najwyższy w sprawie' = reasoning, etc.
    Real production code would keep state.
    """
    if idx == 1:
        return "header"
    if para.startswith("Sąd Najwyższy w sprawie"):
        return "reasoning"
    if "odmawia podjęcia" in para or "uchwala" in para:
        return "disposition"
    return "body"


# ---------- 6  Main CLI ---------------------------------------------------- #

def preprocess_sn_rulings(pdf_path: Path) -> List[Dict[str, Any]]:
    NLP = build_nlp()
    joined, paragraphs = extract_text(pdf_path)
    meta = extract_meta(joined)
    clean = list(clean_text(paragraphs))
    logging.info("Parsed meta: %s", meta)

    records = enrich_paragraphs(clean, meta, NLP)

    # one JSON row per paragraph, .jsonl for easy ingest
    os.makedirs("data/jsonl", exist_ok=True)
    with open(os.path.join("data/jsonl", pdf_path.stem + ".jsonl"), "w") as f:
        for rec in records:
            print(json.dumps(rec, ensure_ascii=False, indent=2))
            f.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__":
    rulings_dir = Path("data/pdfs/sn-rulings")
    pdf_files = list(rulings_dir.glob("*.pdf"))
    for pdf_file in pdf_files:
        preprocess_sn_rulings(pdf_file)
