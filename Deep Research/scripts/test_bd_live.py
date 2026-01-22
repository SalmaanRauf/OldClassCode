#!/usr/bin/env python3
"""
Quick test script for BD MVP components.

Run this to verify:
1. ContextFree API connection works
2. Credentials Agent can query the GPT
3. Opportunity extraction works
4. Full orchestration works

Usage:
    python scripts/test_bd_live.py

Requires: .env file with proper AAD credentials
"""
import asyncio
import sys
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Sample Deep Research output for testing
SAMPLE_DEEP_RESEARCH = """
# Executive Summary

Analysis of CMMC compliance opportunities in the Defense sector reveals significant 
potential for Protiviti engagement. Recent DoD requirements expansion and Hanwha's 
acquisition of Philly Shipyard create immediate needs for compliance services.

## Signals Detected

• CMMC Level 2 requirements expanding to all defense supply chain contractors by 2025
• Hanwha Defense USA leadership changes signal growth initiatives
• DoD increasing audit frequency for existing contractors

## Opportunity Details

• CMMC Compliance Program for Hanwha Defense USA – DoD
  Scope: Cybersecurity and compliance assessment services for CMMC Level 2 certification
  Value: $2.4B (estimated based on similar defense contractor programs)
  Timeline: FY2025-2027
  Incumbent: None (new requirement)
  CMMC Compliance: Level 2 required

• Cybersecurity Assessment for Defense Subcontractor – Huntington Ingalls
  Scope: Risk assessment and remediation planning for NIST 800-171 compliance
  Value: $500M
  Timeline: Q2 2025
  CMMC Compliance: Level 1 required

## Recommended Actions

• Engage Hanwha Defense USA leadership through industry contacts within 30 days
• Propose CMMC readiness assessment as entry point engagement
• Leverage recent CMMC credentials in proposal materials

## Sources

• https://www.defense.gov/cmmc-updates-2025
• https://www.hanwhadefense.com/news/expansion
"""


async def test_opportunity_extraction():
    """Test opportunity extraction from markdown."""
    print("\n" + "="*60)
    print("TEST 1: Opportunity Extraction")
    print("="*60)
    
    from services.opportunity_extractor import OpportunityExtractor
    
    extractor = OpportunityExtractor()
    result = extractor.extract(SAMPLE_DEEP_RESEARCH)
    
    print(f"✓ Executive Summary: {len(result.executive_summary)} chars")
    print(f"✓ Signals Detected: {len(result.signals_detected)} items")
    print(f"✓ Opportunities: {len(result.opportunities)} found")
    
    for i, opp in enumerate(result.opportunities, 1):
        print(f"\n  Opportunity {i}: {opp.title}")
        print(f"    Agency: {opp.agency or 'N/A'}")
        print(f"    Value: {opp.estimated_value or 'N/A'}")
        print(f"    Confidence: {opp.confidence}")
    
    print(f"\n✓ Actions: {len(result.recommended_actions)} items")
    print(f"✓ Citations: {len(result.raw_citations)} URLs")
    
    return result


async def test_credentials_agent(opportunities):
    """Test credentials lookup for extracted opportunities."""
    print("\n" + "="*60)
    print("TEST 2: Credentials Agent (Live API)")
    print("="*60)
    
    # Check env vars
    required_vars = ["CONTEXTFREE_API_URL", "TENANT_ID", "CLIENT_ID", "CLIENT_SECRET", "SCOPE"]
    missing = [v for v in required_vars if not os.getenv(v)]
    
    if missing:
        print(f"⚠ Missing env vars: {missing}")
        print("  Skipping live API test. Set these in .env file.")
        return None
    
    from agents.credentials_agent import CredentialsAgent
    
    print("→ Initializing Credentials Agent from env...")
    agent = CredentialsAgent.from_env()
    
    # Test with first opportunity
    if not opportunities:
        print("⚠ No opportunities to test with")
        return None
    
    opp = opportunities[0]
    print(f"\n→ Looking up credentials for: {opp.title}")
    print(f"  Sector: Defense")
    print(f"  Scope: {opp.scope[:100]}...")
    
    try:
        result = await agent.find_credentials(opp, sector="Defense")
        
        print(f"\n✓ Response received!")
        print(f"  Matches found: {len(result.matches)}")
        print(f"  No matches flag: {result.no_matches_found}")
        
        for i, match in enumerate(result.matches, 1):
            print(f"\n  Credential {i}: {match.title}")
            print(f"    Value: {match.value_provided[:100] if match.value_provided else 'N/A'}...")
            print(f"    URL: {match.url or 'N/A'}")
        
        return result
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("  Check your env vars and network connection")
        return None


async def test_full_orchestration():
    """Test full BD orchestration (optional - takes longer)."""
    print("\n" + "="*60)
    print("TEST 3: Full BD Orchestration")
    print("="*60)
    
    required_vars = ["CONTEXTFREE_API_URL", "TENANT_ID", "CLIENT_ID", "CLIENT_SECRET", "SCOPE"]
    missing = [v for v in required_vars if not os.getenv(v)]
    
    if missing:
        print(f"⚠ Skipping - missing env vars")
        return
    
    from services.bd_orchestrator import BDOrchestrator
    from models.bd_schemas import BDTrigger
    
    trigger = BDTrigger(
        sector="Defense",
        signals=["CMMC"],
        company_focus="Hanwha"
    )
    
    print("→ Running full orchestration...")
    print(f"  Trigger: {trigger.sector} / {trigger.signals}")
    
    def progress(msg):
        print(f"  → {msg}")
    
    try:
        orchestrator = BDOrchestrator()
        report = await orchestrator.run(
            trigger,
            deep_research_output=SAMPLE_DEEP_RESEARCH,
            progress_cb=progress
        )
        
        print(f"\n✓ Report generated!")
        print(f"  Summary: {report.trigger_summary}")
        print(f"  Top Opps: {len(report.top_opportunities)}")
        print(f"  Signals: {report.signals_detected}")
        
        return report
        
    except Exception as e:
        print(f"\n✗ Orchestration failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    print("\n" + "="*60)
    print("BD MVP LIVE TEST")
    print("="*60)
    print("This will test the BD components with sample data.\n")
    
    # Test 1: Extraction (no API needed)
    research = await test_opportunity_extraction()
    
    # Test 2: Credentials Agent (needs API)
    if research and research.opportunities:
        await test_credentials_agent(research.opportunities)
    
    # Test 3: Full orchestration (optional)
    run_full = input("\n\nRun full orchestration test? (y/n): ").strip().lower()
    if run_full == 'y':
        await test_full_orchestration()
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
