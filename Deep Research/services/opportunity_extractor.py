"""
Opportunity Extractor for parsing Deep Research markdown output.

Extracts structured opportunities from the Deep Research report format
documented in NextSteps_POC.md. The expected format includes:

- Executive Summary (paragraph)
- Signals Detected (bullet points)
- Opportunity Details (structured list with values, timelines, etc.)
- Recommended Actions (bullet points)
- Sources (URLs)

Example opportunity format from sample output:
• CMMC Compliance Program for Hanwha Defense USA – Expand compliance...
  Scope: Cybersecurity and compliance services for CMMC Level 2...
  Value: $2.4B (estimated based on similar contracts)
  Timeline: FY2025-2027
  Incumbent: None (new requirement)
  CMMC Compliance: Level 2 required
"""
import re
import logging
from typing import List, Dict, Optional, Tuple, Set

from models.bd_schemas import Opportunity, DeepResearchOutput, OpportunityExtractionDiagnostics

logger = logging.getLogger(__name__)


class OpportunityExtractor:
    """Extract structured data from Deep Research markdown output.
    
    Parses the markdown report into:
    - Executive summary
    - Signals detected
    - Individual opportunities
    - Recommended actions
    - Source citations
    
    Example:
        extractor = OpportunityExtractor()
        result = extractor.extract(deep_research_markdown)
        for opp in result.opportunities:
            print(f"{opp.title}: {opp.estimated_value}")
    """
    
    # Section header patterns
    SECTION_PATTERNS = {
        "executive_summary": r"(?:^|\n)#+\s*Executive\s+Summary\s*\n",
        "signals": r"(?:^|\n)#+\s*(?:Signals?\s+Detected|Key\s+Signals?)\s*\n",
        "opportunities": r"(?:^|\n)#+\s*(?:Opportunity\s+Details?|Opportunities?|Contract\s+Opportunities?|Deep\s+Research\s+Findings|Final\s+Report)\s*\n",
        "actions": r"(?:^|\n)#+\s*(?:Recommended\s+(?:Actions?|Next\s+Steps?)|Next\s+Steps?)\s*\n",
        "sources": r"(?:^|\n)#+\s*(?:Sources?|References?|Citations?)\s*\n"
    }
    
    # Opportunity field patterns
    FIELD_PATTERNS = {
        "scope": r"Scope:\s*(.+?)(?=\n\s*(?:Value|Timeline|Incumbent|CMMC|$))",
        "value": r"(?:Value|Est(?:imated)?\s*Value):\s*(.+?)(?=\n|$)",
        "timeline": r"Timeline:\s*(.+?)(?=\n|$)",
        "incumbent": r"Incumbent:\s*(.+?)(?=\n|$)",
        "cmmc": r"(?:CMMC\s*(?:Level|Compliance|Requirement[s]?)?|Compliance):\s*(.+?)(?=\n|$)"
    }

    SERVICE_PREFIX_PATTERN = re.compile(
        r"^(?:u\.s\.\s+)?(?:navy|army|air\s*force|space\s*force|usace|dla|dod|defense|marine\s+corps)\b",
        re.IGNORECASE
    )
    CONTRACT_KEYWORDS = (
        "solicitation", "rfp", "idiq", "contract", "procurement", "program",
        "facility", "maintenance", "integration", "assessment", "support", "services",
        "upgrade", "cmmc", "timeline", "value", "award"
    )
    
    def extract(self, markdown: str) -> DeepResearchOutput:
        """Extract structured data from Deep Research markdown.
        
        Args:
            markdown: Raw markdown output from Deep Research
            
        Returns:
            DeepResearchOutput with parsed sections and opportunities
        """
        if not markdown or not markdown.strip():
            return DeepResearchOutput()
        
        # Split into sections
        sections = self._split_sections(markdown)

        opportunities_section = sections.get("opportunities", "")
        opportunities = self._extract_opportunities(opportunities_section)
        extraction_method = "section_structured" if opportunities_section.strip() else "none"

        # Fallback extraction for narrative reports when canonical section parsing yields nothing.
        if not opportunities:
            fallback_opportunities = self._extract_opportunities_from_narrative(markdown)
            if fallback_opportunities:
                opportunities = fallback_opportunities
                extraction_method = "narrative_fallback"

        opportunities = self._dedupe_opportunities(opportunities)

        candidate_signal_count = self._count_opportunity_signals(markdown)
        extraction_diagnostics = self._build_extraction_diagnostics(
            opportunities=opportunities,
            extraction_method=extraction_method,
            candidate_signal_count=candidate_signal_count
        )

        # Extract each component
        return DeepResearchOutput(
            executive_summary=self._extract_executive_summary(sections),
            signals_detected=self._extract_bullets(sections.get("signals", "")),
            opportunities=opportunities,
            recommended_actions=self._extract_bullets(sections.get("actions", "")),
            raw_citations=self._extract_citations(sections.get("sources", ""), markdown),
            extraction_diagnostics=extraction_diagnostics
        )
    
    def _split_sections(self, markdown: str) -> Dict[str, str]:
        """Split markdown into named sections."""
        sections = {}
        
        # Find all section positions
        section_positions: List[Tuple[str, int, int]] = []
        
        for name, pattern in self.SECTION_PATTERNS.items():
            for match in re.finditer(pattern, markdown, re.IGNORECASE):
                section_positions.append((name, match.start(), match.end()))
        
        # Sort by position
        section_positions.sort(key=lambda x: x[1])
        
        # Extract content between sections
        for i, (name, start, header_end) in enumerate(section_positions):
            if i + 1 < len(section_positions):
                end = section_positions[i + 1][1]
            else:
                end = len(markdown)
            
            content = markdown[header_end:end].strip()
            sections[name] = content
        
        return sections
    
    def _extract_executive_summary(self, sections: Dict[str, str]) -> str:
        """Extract executive summary paragraph."""
        summary = sections.get("executive_summary", "")
        
        # Get first paragraph (up to double newline or next header)
        if summary:
            # Remove any remaining headers
            summary = re.sub(r"^#+\s+.+\n", "", summary)
            # Get first paragraph
            paragraphs = re.split(r"\n\s*\n", summary)
            if paragraphs:
                return paragraphs[0].strip()
        
        return ""
    
    def _extract_bullets(self, section: str) -> List[str]:
        """Extract bullet points from a section."""
        if not section:
            return []
        
        bullets = []
        # Match various bullet formats: •, -, *, numbers
        pattern = r"(?:^|\n)\s*(?:[•\-\*]|\d+[\.\)])\s+(.+?)(?=\n\s*(?:[•\-\*]|\d+[\.\)]|$)|$)"
        
        for match in re.finditer(pattern, section, re.DOTALL):
            bullet_text = match.group(1).strip()
            # Clean up multi-line bullets
            bullet_text = re.sub(r"\s+", " ", bullet_text)
            if bullet_text:
                bullets.append(bullet_text)
        
        # Fallback: split by newlines if no bullets found
        if not bullets:
            for line in section.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    bullets.append(line)
        
        return bullets[:10]  # Limit to 10 items
    
    def _extract_opportunities(self, section: str) -> List[Opportunity]:
        """Extract individual opportunities from the opportunities section."""
        if not section:
            return []
        
        opportunities = []
        
        # Split by opportunity markers (bullet with title)
        # Pattern: bullet followed by title with agency
        opp_pattern = r"(?:^|\n)\s*[•\-\*]\s*(.+?)(?=\n\s*[•\-\*]|\n\s*#+|$)"
        
        blocks = re.findall(opp_pattern, section, re.DOTALL)
        
        if not blocks:
            # Fallback: try numbered list
            blocks = re.findall(r"(?:^|\n)\s*\d+[\.\)]\s*(.+?)(?=\n\s*\d+[\.\)]|\n\s*#+|$)", section, re.DOTALL)
        
        for block in blocks:
            opp = self._parse_opportunity_block(block)
            if opp:
                opportunities.append(opp)
        
        return opportunities[:10]  # Limit to 10

    def _extract_opportunities_from_narrative(self, markdown: str) -> List[Opportunity]:
        """Best-effort extraction from full narrative markdown."""
        if not markdown:
            return []

        opportunities: List[Opportunity] = []
        lines = markdown.splitlines()
        idx = 0
        max_lines = len(lines)
        while idx < max_lines:
            current = lines[idx].strip()
            if not self._looks_like_opportunity_title(current):
                idx += 1
                continue

            block_lines = [current]
            next_idx = idx + 1
            while next_idx < max_lines:
                candidate = lines[next_idx].strip()
                if not candidate:
                    block_lines.append("")
                    next_idx += 1
                    continue
                if candidate.startswith("#"):
                    break
                if self._looks_like_opportunity_title(candidate):
                    break
                block_lines.append(lines[next_idx])
                next_idx += 1

            block_text = "\n".join(block_lines).strip()
            parsed = self._parse_opportunity_block(block_text)
            if parsed and self._has_opportunity_substance(parsed):
                opportunities.append(parsed)
            idx = next_idx

        return opportunities[:10]
    
    def _parse_opportunity_block(self, block: str) -> Optional[Opportunity]:
        """Parse a single opportunity block into an Opportunity object."""
        if not block or len(block.strip()) < 20:
            return None
        
        lines = block.strip().split("\n")
        if not lines:
            return None
        
        # First line is title (possibly with agency)
        title_line = lines[0].strip()
        title_line = re.sub(r"^\d+[\.\)]\s+", "", title_line).strip()
        if ":" in title_line:
            prefix, remainder = title_line.split(":", 1)
            if self.SERVICE_PREFIX_PATTERN.search(prefix.strip()) and remainder.strip():
                title_line = remainder.strip()
        title, agency = self._parse_title_agency(title_line)
        
        if not title:
            return None
        
        # Extract remaining fields from block
        block_text = block
        
        scope = self._extract_field(block_text, "scope") or title_line
        value = self._extract_field(block_text, "value")
        timeline = self._extract_field(block_text, "timeline")
        incumbent = self._extract_field(block_text, "incumbent")
        cmmc = self._extract_field(block_text, "cmmc")
        
        # Determine confidence based on available data
        confidence = self._assess_confidence(value, timeline, bool(cmmc))
        
        # Extract citations from block
        citations = self._extract_urls(block_text)
        
        return Opportunity(
            title=title,
            agency=agency,
            scope=scope[:500] if scope else "",  # Limit scope length
            estimated_value=value,
            timeline=timeline,
            incumbent=incumbent,
            cmmc_level=cmmc,
            confidence=confidence,
            citations=citations
        )
    
    def _parse_title_agency(self, title_line: str) -> Tuple[str, Optional[str]]:
        """Parse title and agency from title line.
        
        Format: "Title – Agency" or "Title - Agency" or just "Title"
        """
        # Check for separator
        separators = [" – ", " - ", " — "]
        for sep in separators:
            if sep in title_line:
                parts = title_line.split(sep, 1)
                return parts[0].strip(), parts[1].strip() if len(parts) > 1 else None
        
        # Check for agency in parentheses
        match = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", title_line)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        return title_line.strip(), None

    def _looks_like_opportunity_title(self, line: str) -> bool:
        """Heuristic title detector for narrative fallback parsing."""
        if not line:
            return False
        lower = line.lower()
        if len(line) < 20 or len(line) > 280:
            return False
        if lower.startswith(("introduction", "conclusion", "summary", "sources", "recommendation", "impact")):
            return False

        numbered = re.match(r"^\d+[\.\)]\s+", line) is not None
        service_prefixed = self.SERVICE_PREFIX_PATTERN.search(lower) is not None and any(
            delimiter in line for delimiter in (" - ", " – ", " — ", ":")
        )
        has_contract_keyword = any(keyword in lower for keyword in self.CONTRACT_KEYWORDS)
        keyword_structured = has_contract_keyword and any(
            delimiter in line for delimiter in (" - ", " – ", " — ", ":")
        ) and any(
            branch in lower for branch in ("navy", "army", "air force", "space force", "usace", "dla", "dod", "defense")
        )

        return (numbered and has_contract_keyword) or service_prefixed or keyword_structured

    def _has_opportunity_substance(self, opportunity: Opportunity) -> bool:
        """Require at least one structural indicator to reduce false positives."""
        return bool(
            opportunity.estimated_value
            or opportunity.timeline
            or opportunity.cmmc_level
            or "solicitation" in (opportunity.scope or "").lower()
            or "contract" in (opportunity.scope or "").lower()
        )

    def _count_opportunity_signals(self, markdown: str) -> int:
        """Count opportunity-like signals in source text."""
        if not markdown:
            return 0
        signal_patterns = [
            r"\bsolicitation\b",
            r"\brfp\b",
            r"\bidiq\b",
            r"\bcontract\b",
            r"\bcmmc\b",
            r"\bvalue\s*:",
            r"\btimeline\s*:",
            r"\$\d",
        ]
        count = 0
        lower = markdown.lower()
        for pattern in signal_patterns:
            if re.search(pattern, lower):
                count += 1
        return count

    def _build_extraction_diagnostics(
        self,
        opportunities: List[Opportunity],
        extraction_method: str,
        candidate_signal_count: int
    ) -> OpportunityExtractionDiagnostics:
        """Build deterministic extraction diagnostics for orchestrator gating."""
        parsed_count = len(opportunities)
        if parsed_count > 0:
            confidence = "High" if extraction_method == "section_structured" else "Medium"
            return OpportunityExtractionDiagnostics(
                status="Parsed",
                reason=f"Parsed {parsed_count} opportunities using {extraction_method}.",
                opportunities_extracted_count=parsed_count,
                extraction_method=extraction_method,
                extraction_confidence=confidence,
                candidate_signal_count=candidate_signal_count
            )

        if candidate_signal_count >= 3:
            return OpportunityExtractionDiagnostics(
                status="Extraction Failed",
                reason="Opportunity-like signals were present but no structured opportunities were parsed.",
                opportunities_extracted_count=0,
                extraction_method=extraction_method if extraction_method != "none" else "narrative_fallback",
                extraction_confidence="Low",
                candidate_signal_count=candidate_signal_count
            )

        return OpportunityExtractionDiagnostics(
            status="No Opportunities",
            reason="No opportunity-like content was detected in the report.",
            opportunities_extracted_count=0,
            extraction_method=extraction_method,
            extraction_confidence="Low",
            candidate_signal_count=candidate_signal_count
        )

    def _dedupe_opportunities(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        """Deduplicate opportunities by normalized title, preserving first occurrence."""
        deduped: List[Opportunity] = []
        seen: Set[str] = set()
        for opp in opportunities:
            key = re.sub(r"[^a-z0-9]+", " ", (opp.title or "").lower()).strip()
            if not key:
                continue
            if key in seen:
                continue
            deduped.append(opp)
            seen.add(key)
        return deduped
    
    def _extract_field(self, text: str, field_name: str) -> Optional[str]:
        """Extract a specific field value from text."""
        pattern = self.FIELD_PATTERNS.get(field_name)
        if not pattern:
            return None
        
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            # Clean up
            value = re.sub(r"\s+", " ", value)
            return value if value else None
        
        return None
    
    def _assess_confidence(
        self,
        value: Optional[str],
        timeline: Optional[str],
        has_compliance: bool
    ) -> str:
        """Assess confidence level based on available data."""
        score = 0
        
        if value and ("$" in value or "million" in value.lower() or "billion" in value.lower()):
            score += 2
        if timeline:
            score += 1
        if has_compliance:
            score += 1
        
        if score >= 3:
            return "High"
        elif score >= 1:
            return "Medium"
        else:
            return "Low"
    
    def _extract_citations(self, sources_section: str, full_markdown: str) -> List[str]:
        """Extract citation URLs from sources section and full document."""
        urls = set()
        
        # Extract from sources section
        if sources_section:
            urls.update(self._extract_urls(sources_section))
        
        # Also extract URLs from entire document
        all_urls = self._extract_urls(full_markdown)
        urls.update(all_urls)
        
        return list(urls)[:20]  # Limit to 20 citations
    
    def _extract_urls(self, text: str) -> List[str]:
        """Extract URLs from text."""
        if not text:
            return []
        
        # URL pattern
        pattern = r"https?://[^\s\)\]\"'<>]+"
        urls = re.findall(pattern, text)
        
        # Clean up trailing punctuation
        cleaned = []
        for url in urls:
            url = url.rstrip(".,;:")
            if url and len(url) > 10:
                cleaned.append(url)
        
        return cleaned
