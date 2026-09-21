"""VRS fork: request/response models for POST /alert/enrich.

Kept in a sibling file so plugins/restapi/models.py stays identical to upstream
(zero merge cost). Imported by plugins/restapi/commands.py.
"""
from typing import Optional

from pydantic import BaseModel, Field


class AlertEnrichRequest(BaseModel):
    signal_key: str = Field(..., description="Matches a signals/*.ps1 Key in the VRSInfra alerting/ repo. Selects the enrichment profile.")
    severity: str = Field(..., description="Sev1..Sev4 from the signal definition.")
    # Pydantic v2 coerces numeric strings to int -- Seq sends NotificationProperty
    # values as strings, so "1" arrives and gets cast to 1 cleanly.
    pushover_priority: int = Field(..., description="-2..1 Pushover priority.")
    pushover_title: str = Field(..., description="Base Pushover title (pre-enrichment).")
    pushover_message: str = Field(..., description="Base Pushover message (pre-enrichment).")
    fired_at: Optional[str] = Field(None, description="ISO timestamp of the firing event (Seq @t).")
    sample_message: Optional[str] = Field(None, description="Rendered message of the sample event that caused the alert.")
    seq_url: Optional[str] = Field(None, description="Link back to the Seq query results for this alert.")
    event_count: Optional[int] = Field(None, description="Count from the alert's Having clause.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "signal_key": "player-disconnect",
                "severity": "Sev1",
                "pushover_priority": 1,
                "pushover_title": "VRS Sev1: Player disconnects clustering",
                "pushover_message": "Player disconnect cluster on Prod.",
                "fired_at": "2026-05-22T23:08:11Z",
                "sample_message": "disconnecting client[3]: timeout",
                "seq_url": "https://logs.victorromeosierra.com/#/events?...",
                "event_count": 3
            }
        }
    }


class AlertEnrichResponse(BaseModel):
    delivered: bool = Field(..., description="True if Pushover accepted the message.")
    enriched: bool = Field(..., description="True if at least one live context line was attached; false on timeout or fallback.")
    pushover_status: Optional[int] = Field(None, description="HTTP status from api.pushover.net.")
    notes: Optional[str] = Field(None, description="Diagnostic info (e.g. why enrichment was partial).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "delivered": True,
                "enriched": True,
                "pushover_status": 200,
                "notes": None
            }
        }
    }
