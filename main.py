import os
from typing import List, Optional, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Borrower, Lender, MediaItem, LoanAsset, LoanEstimation, LoanRequest, BYOBLead

app = FastAPI(title="Lender Service Provider (LSP)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")


def serialize_doc(doc):
    if not doc:
        return None
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert datetime to iso
    for k, v in list(d.items()):
        try:
            import datetime
            if isinstance(v, (datetime.datetime, datetime.date)):
                d[k] = v.isoformat()
        except Exception:
            pass
    return d


# Estimation logic
class EstimateInput(BaseModel):
    asset: LoanAsset

class CreateLoanInput(BaseModel):
    borrower: Borrower
    asset: LoanAsset
    media: List[MediaItem] = Field(default_factory=list)

class ModifyOfferInput(BaseModel):
    offer_amount: float
    lender_note: Optional[str] = None

class StatusUpdateInput(BaseModel):
    action: Literal["Approve", "Reject", "Modify"]
    data: Optional[ModifyOfferInput] = None

class BorrowerQuery(BaseModel):
    mobile: str

class BYOBInput(BaseModel):
    lender: Lender
    borrower: Borrower
    asset: LoanAsset


def estimate_value(asset: LoanAsset) -> LoanEstimation:
    base_map = {
        "vehicle": {
            "2-wheeler": 80000,
            "3-wheeler": 200000,
            "4-wheeler": 600000,
        },
        "electronics": {
            "laptop": 60000,
            "mobile": 40000,
            "other": 20000,
        },
    }
    subtype_key = asset.subtype.lower()
    # Normalize subtype keys to match map
    if asset.category == "vehicle":
        if subtype_key not in {"2-wheeler", "3-wheeler", "4-wheeler"}:
            subtype_key = "2-wheeler"
    else:
        if subtype_key not in {"laptop", "mobile", "other"}:
            subtype_key = "other"

    base = base_map[asset.category][subtype_key]

    year = asset.year or 2020
    try:
        import datetime
        age = max(0, datetime.datetime.now().year - int(year))
    except Exception:
        age = 4

    # Depreciation curve
    if asset.category == "vehicle":
        # 15% first year, 10% subsequently
        value = base * (0.85) * (0.9 ** max(0, age - 1))
    else:
        # electronics depreciate faster
        value = base * (0.7) * (0.75 ** max(0, age))

    condition_factor = {
        "excellent": 1.05,
        "good": 1.0,
        "fair": 0.85,
        "poor": 0.7,
    }.get((asset.condition or "good"), 1.0)

    estimated = max(5000.0, value * condition_factor)
    # LTV policy
    ltv = 0.6 if asset.category == "vehicle" else 0.5
    suggested = round(estimated * ltv, 0)
    return LoanEstimation(estimated_value=round(estimated, 0), suggested_loan=suggested, ltv=ltv)


@app.get("/")
def root():
    return {"message": "Lender Service Provider (LSP) API"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = os.getenv("DATABASE_NAME") or "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:60]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:60]}"
    return response


# Estimation endpoint
@app.post("/api/estimate", response_model=LoanEstimation)
def api_estimate(payload: EstimateInput):
    return estimate_value(payload.asset)


# Create loan request
@app.post("/api/loan-requests")
def create_loan_request(payload: CreateLoanInput):
    estimation = estimate_value(payload.asset)
    req = LoanRequest(
        borrower=payload.borrower,
        asset=payload.asset,
        estimation=estimation,
        media=payload.media,
        status="Pending",
        source="platform",
    )
    inserted_id = create_document("loanrequest", req.model_dump())
    return {"id": inserted_id, "status": req.status, "estimation": estimation.model_dump()}


# List loan requests (for lenders)
@app.get("/api/loan-requests")
def list_loan_requests(status: Optional[str] = None, source: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    if source:
        q["source"] = source
    docs = get_documents("loanrequest", q)
    return [serialize_doc(d) for d in docs]


# Get single loan request details
@app.get("/api/loan-requests/{req_id}")
def get_loan_request(req_id: str):
    doc = db["loanrequest"].find_one({"_id": ObjectId(req_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    return serialize_doc(doc)


# Update status / offer
@app.patch("/api/loan-requests/{req_id}/status")
def update_status(req_id: str, payload: StatusUpdateInput):
    doc = db["loanrequest"].find_one({"_id": ObjectId(req_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    update = {}
    if payload.action == "Approve":
        update["status"] = "Approved"
    elif payload.action == "Reject":
        update["status"] = "Rejected"
    elif payload.action == "Modify":
        if not payload.data or payload.data.offer_amount is None:
            raise HTTPException(status_code=400, detail="offer_amount required for Modify")
        update["status"] = "Modified"
        update["offer_amount"] = payload.data.offer_amount
        if payload.data.lender_note:
            update["lender_note"] = payload.data.lender_note

    if not update:
        raise HTTPException(status_code=400, detail="No update provided")

    db["loanrequest"].update_one({"_id": ObjectId(req_id)}, {"$set": update})
    updated = db["loanrequest"].find_one({"_id": ObjectId(req_id)})
    return serialize_doc(updated)


# Borrower can view their requests by mobile
@app.get("/api/borrower/requests")
def borrower_requests(mobile: str):
    docs = get_documents("loanrequest", {"borrower.mobile": mobile})
    return [serialize_doc(d) for d in docs]


# BYOB - Bring Your Own Borrower
@app.post("/api/byob")
def create_byob(payload: BYOBInput):
    estimation = estimate_value(payload.asset)
    req = LoanRequest(
        borrower=payload.borrower,
        asset=payload.asset,
        estimation=estimation,
        media=[],
        status="Pending",
        source="byob",
        lender_id=(payload.lender.company or payload.lender.name or "lender")
    )
    inserted_id = create_document("loanrequest", req.model_dump())
    return {"id": inserted_id, "status": req.status, "estimation": estimation.model_dump()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
