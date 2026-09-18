from datetime import datetime

from pydantic import BaseModel


class CaseCreate(BaseModel):
    case_number: str
    crime_type: str
    victim_complaint: str | None = None


class CaseOut(BaseModel):
    id: str
    case_number: str
    crime_type: str
    victim_complaint: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseNoteCreate(BaseModel):
    body: str
