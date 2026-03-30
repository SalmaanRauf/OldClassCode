"""
Tests for ProConnect quick lookup precision and fallback behavior.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.proconnect_lookup_logic import match_person_in_people, resolve_person_tiered  # noqa: E402


def test_match_person_in_people_does_not_match_on_shared_first_name_alone() -> None:
    people = [
        {
            "id": "nancy-1",
            "firstName": "Nancy",
            "lastName": "Cole",
            "title": "Senior Counsel",
            "department": "Legal",
        }
    ]

    assert match_person_in_people("Nancy Jardini", people) is None


def test_resolve_person_tiered_uses_exact_account_scoped_person_search_fallback() -> None:
    class FakeClient:
        def search_prospects(self, search_text):
            if search_text == "Jason Dandridge":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-77",
                                    "accountId": "001-to",
                                    "companyName": "Federal National Mortgage Association (Fannie Mae)",
                                    "name": "Jason Dandridge",
                                    "title": "Head of Operations",
                                    "emailAddress": "jason.dandridge@fanniemae.com",
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
            del zoom_info_account_id, department, sfdc_job_function, page, size
            return {"success": True, "status_code": 200, "data": {"employees": []}}

    account = {
        "id": "001-to",
        "zoomInfoAccountId": "72074644",
        "keyBuyers": [],
    }

    resolution = resolve_person_tiered(
        client=FakeClient(),
        account=account,
        person_name="Jason Dandridge",
        department_hint="Operations",
    )

    assert resolution["status"] == "matched"
    assert resolution["match_source"] == "person_search"
    assert resolution["matched_person"]["name"] == "Jason Dandridge"
