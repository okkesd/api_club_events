from pydantic import BaseModel, EmailStr
from typing import Optional

# --- USER SCHEMAS ---

# What the frontend sends to US
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    club_name: str
    description: Optional[str] = None

# What WE send back to the frontend (No password!)
class UserResponse(BaseModel):
    id: str
    email: EmailStr
    club_name: str
    
    class Config:
        # This tells Pydantic to read data even if it's an ORM object (not just a dict)
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None