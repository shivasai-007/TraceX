from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    investigator_name: str
    investigator_id: str


class InvestigatorCreate(BaseModel):
    badge_id: str
    full_name: str
    email: EmailStr
    password: str
    unit: str | None = None
