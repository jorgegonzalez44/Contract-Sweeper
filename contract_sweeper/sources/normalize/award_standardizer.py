"""Award standardization and normalization."""
from __future__ import annotations

from typing import Any, Dict, List

# Standard award columns used across all federal sources
STANDARD_AWARD_COLUMNS = [
    "award_id",
    "award_unique_id",
    "recipient_name",
    "recipient_uei",
    "recipient_duns",
    "funding_agency_name",
    "funding_agency_code",
    "awarding_agency_name",
    "awarding_agency_code",
    "award_type",
    "award_description",
    "action_date",
    "award_date",
    "award_amount",
    "recipient_location_state",
    "recipient_location_zip5",
    "naics_code",
    "psc_code",
    "sam_registration_status",
    "source",
    "source_record_id",
]

# Flow columns for non-award records (grants, assistance, etc.)
FLOW_STANDARD_COLUMNS_V2 = [
    "flow_id",
    "flow_type",
    "source_agency",
    "recipient_name",
    "recipient_uei",
    "recipient_duns",
    "amount",
    "fiscal_year",
    "effective_date",
    "recipient_state",
    "source",
    "source_record_id",
    "lineage",
]


class AwardStandardizer:
    """Normalize and standardize award records."""

    @staticmethod
    def standardize_award(raw_award: Dict[str, Any]) -> Dict[str, Any]:
        """Convert raw award to standard format."""
        return {
            col: raw_award.get(col) for col in STANDARD_AWARD_COLUMNS
        }

    @staticmethod
    def standardize_flow(raw_flow: Dict[str, Any]) -> Dict[str, Any]:
        """Convert raw flow record to standard format."""
        return {
            col: raw_flow.get(col) for col in FLOW_STANDARD_COLUMNS_V2
        }
