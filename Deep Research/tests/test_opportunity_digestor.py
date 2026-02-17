"""
Tests for ATLAS opportunity digest parser behavior.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.opportunity_digestor import OpportunityDigestor


def test_coerce_opportunities_maps_source_url_to_citations():
    digestor = OpportunityDigestor(kernel=object(), exec_settings=object())
    opportunities = digestor._coerce_opportunities(
        [
            {
                "title": "MAPS IDIQ",
                "scope": "Professional services contract",
                "source_url": "https://sam.gov/opp/1234/view",
                "confidence": "High",
            }
        ],
        max_opportunities=10,
    )

    assert len(opportunities) == 1
    assert opportunities[0].citations == ["https://sam.gov/opp/1234/view"]


def test_coerce_opportunities_handles_missing_source_url():
    digestor = OpportunityDigestor(kernel=object(), exec_settings=object())
    opportunities = digestor._coerce_opportunities(
        [
            {
                "title": "PM UAS S/VTOL",
                "scope": "Prototype challenge",
                "confidence": "Medium",
            }
        ],
        max_opportunities=10,
    )

    assert len(opportunities) == 1
    assert opportunities[0].citations == []

