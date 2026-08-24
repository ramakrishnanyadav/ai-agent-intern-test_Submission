"""
Ingestion & Markdown Parsing Module for Aster & Row Knowledge Base.
Parses frontmatter metadata and chunks documents by headings while preserving metadata.
"""

import os
import re
import yaml
from pathlib import Path
from typing import List, Dict, Any, Tuple
from src.contracts import DocumentChunk, Status, Authority, Visibility


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Extracts YAML frontmatter from markdown content.
    Returns (frontmatter_dict, body_text).
    """
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if not match:
        return {}, content
    
    yaml_text = match.group(1)
    body_text = match.group(2)
    try:
        metadata = yaml.safe_load(yaml_text) or {}
    except Exception:
        metadata = {}
    return metadata, body_text


def map_metadata_to_enums(metadata: Dict[str, Any], filename: str) -> Tuple[Status, Authority, Visibility]:
    """
    Maps raw frontmatter fields to Status, Authority, and Visibility enums.
    """
    raw_status = str(metadata.get("status", "active")).lower().strip()
    if raw_status == "active":
        status = Status.ACTIVE
    elif raw_status == "superseded":
        status = Status.SUPERSEDED
    elif raw_status == "draft":
        status = Status.DRAFT
    else:
        status = Status.ACTIVE

    raw_audience = str(metadata.get("audience", "customer")).lower().strip()
    raw_authority = str(metadata.get("policy_authority", "official")).lower().strip()
    customer_answering = metadata.get("customer_answering", True)

    # Determine Visibility
    if raw_audience == "internal" or customer_answering is False or raw_authority == "none":
        visibility = Visibility.INTERNAL
    else:
        visibility = Visibility.CUSTOMER

    # Determine Authority
    if raw_authority == "none" or customer_answering is False:
        authority = Authority.INTERNAL
    elif raw_audience == "internal":
        authority = Authority.SUPPORT_GUIDANCE if raw_authority == "official" else Authority.INTERNAL
    elif "product" in filename.lower() or "tumbler" in filename.lower():
        authority = Authority.OFFICIAL_PRODUCT
    else:
        authority = Authority.OFFICIAL_POLICY

    return status, authority, visibility


def chunk_markdown_document(
    filepath: str,
    filename: str,
    content: str
) -> List[DocumentChunk]:
    """
    Chunks a markdown document by headings while preserving metadata.
    """
    metadata, body = parse_frontmatter(content)
    status, authority, visibility = map_metadata_to_enums(metadata, filename)
    
    doc_id = str(metadata.get("document_id", filename))
    title = str(metadata.get("title", filename.replace(".md", "").replace("-", " ").title()))
    effective_date = metadata.get("effective_date")
    if effective_date is not None:
        effective_date = str(effective_date)
    
    # Infer category from document ID or title
    category = filename.split("-")[1] if "-" in filename else "general"

    # Extract Document Title (# Heading) if present
    doc_title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    doc_title = doc_title_match.group(1).strip() if doc_title_match else title

    # Split by level 2 headings (## Heading)
    raw_sections = re.split(r"\n(?=##\s+)", body)
    chunks: List[DocumentChunk] = []

    chunk_idx = 0
    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        lines = section.splitlines()
        # Skip pure title preamble if it only contains the '# Title' line with no content body
        if len(lines) == 1 and lines[0].startswith("# "):
            continue
        
        # If preamble has content before any ## heading
        if lines[0].startswith("# ") and not lines[0].startswith("## "):
            heading = doc_title
            # Filter out the '# Title' line from preamble if followed by text
            sub_lines = [l for l in lines if not l.startswith("# ")]
            if not sub_lines:
                continue
            section_body = "\n".join(sub_lines).strip()
        elif lines[0].startswith("## "):
            heading = lines[0].replace("## ", "").strip()
            section_body = section
        else:
            heading = doc_title
            section_body = section

        chunk_idx += 1
        chunk_id = f"{filename}#{chunk_idx}"
        chunk_text = f"# {doc_title}\n\n{section_body}"
        
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                text=chunk_text,
                filename=filename,
                title=doc_title,
                heading=heading,
                document_id=doc_id,
                status=status,
                authority=authority,
                visibility=visibility,
                effective_date=effective_date,
                category=category,
            )
        )

    return chunks


def load_knowledge_base(kb_dir: str) -> List[DocumentChunk]:
    """
    Loads all markdown files in kb_dir and returns a list of DocumentChunks.
    """
    all_chunks: List[DocumentChunk] = []
    kb_path = Path(kb_dir)
    
    # Sort files to ensure deterministic ingestion order
    for file_path in sorted(kb_path.glob("*.md")):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        filename = file_path.name
        file_chunks = chunk_markdown_document(str(file_path), filename, content)
        all_chunks.extend(file_chunks)

    return all_chunks
