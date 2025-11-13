"""
Database Schemas for Lender Service Provider (LSP)

Each Pydantic model maps to a MongoDB collection (lowercased class name).
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

# Core domain schemas
class Borrower(BaseModel):
    name: str
    mobile: str
    city: str

class Lender(BaseModel):
    name: str
    mobile: Optional[str] = None
    company: Optional[str] = None

class MediaItem(BaseModel):
    kind: Literal["photo", "video"]
    url: str
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None

class LoanAsset(BaseModel):
    category: Literal["vehicle", "electronics"]
    subtype: str  # e.g., "2-wheeler", "laptop", etc.
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = Field(None, description="Manufacture/Purchase year")
    condition: Optional[Literal["excellent", "good", "fair", "poor"]] = "good"
    notes: Optional[str] = None

class LoanEstimation(BaseModel):
    estimated_value: float
    suggested_loan: float
    ltv: float

class LoanRequest(BaseModel):
    borrower: Borrower
    asset: LoanAsset
    estimation: LoanEstimation
    status: Literal["Pending", "Approved", "Rejected", "Modified"] = "Pending"
    offer_amount: Optional[float] = None
    lender_note: Optional[str] = None
    media: List[MediaItem] = []
    source: Literal["platform", "byob"] = "platform"
    lender_id: Optional[str] = None

class BYOBLead(BaseModel):
    lender: Lender
    borrower: Borrower
    asset: LoanAsset
    estimation: Optional[LoanEstimation] = None
    status: Literal["Pending", "In-Review", "Completed"] = "Pending"

# Expose lightweight schema examples for viewers (optional helper endpoint can serve these)
