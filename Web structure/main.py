import os
import re
import io
import zlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="VendorGuard Backend API",
    description="API-first Autonomous Counterfactual Negotiator backend",
    version="2.0.0"
)

# Enable CORS for frontend and external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas
class Redlines(BaseModel):
    soft: str
    balanced: str
    firm: str

class Acceptance(BaseModel):
    soft: int
    balanced: int
    firm: int

class Finding(BaseModel):
    title: str
    clause: str
    severity: str
    exposure_inr: int
    why: str
    original: str
    redlines: Redlines
    acceptance: Acceptance

class AnalysisResponse(BaseModel):
    risk_score: int
    total_exposure_inr: int
    exposure_after_inr: int
    findings: List[Finding]

# Benchmark Sample Findings for the built-in Master Services Agreement Demo
SAMPLE_FINDINGS_POOL = [
    {
        "title": "Unlimited Liability",
        "clause": "9.2",
        "severity": "critical",
        "exposure_inr": 50000000,
        "why": "Client bears uncapped liability for any data breach or service failure. One incident could exceed the whole contract value many times over.",
        "original": "Client shall be liable for all losses, damages and costs arising from use of the Services, without limitation.",
        "redlines": {
            "soft": "Each party's aggregate liability shall not exceed three (3) times the fees paid in the 12 months preceding the claim.",
            "balanced": "Vendor's aggregate liability shall not exceed fees paid in the 12 months preceding the claim.",
            "firm": "Vendor's aggregate liability shall not exceed fees paid in the 12 months preceding the claim, excluding claims arising from Vendor's gross negligence, which shall be uncapped."
        },
        "acceptance": {"soft": 88, "balanced": 72, "firm": 46}
    },
    {
        "title": "Auto-Renewal Trap",
        "clause": "14.1",
        "severity": "high",
        "exposure_inr": 3840000,
        "why": "Contract silently renews for 3 years unless notice is given 90 days before expiry. Missing the window locks in ₹38.4L of unwanted fees.",
        "original": "This Agreement shall automatically renew for successive three (3) year terms unless terminated by written notice no less than ninety (90) days prior to expiry.",
        "redlines": {
            "soft": "This Agreement shall renew for successive one (1) year terms unless either party gives sixty (60) days' written notice.",
            "balanced": "This Agreement shall renew for successive one (1) year terms unless either party gives thirty (30) days' written notice, and Vendor shall send a renewal reminder 60 days before expiry.",
            "firm": "This Agreement shall not renew automatically. Renewal requires written agreement signed by both parties."
        },
        "acceptance": {"soft": 91, "balanced": 78, "firm": 52}
    },
    {
        "title": "Uncapped Price Escalation",
        "clause": "6.4",
        "severity": "high",
        "exposure_inr": 1200000,
        "why": "Vendor may raise fees at any time with 7 days' notice and no ceiling.",
        "original": "Vendor may revise the Fees at any time upon seven (7) days' written notice to Client.",
        "redlines": {
            "soft": "Vendor may revise Fees once per year with sixty (60) days' notice, not exceeding 10%.",
            "balanced": "Vendor may revise Fees once per contract year with sixty (60) days' notice, capped at the lower of 5% or CPI.",
            "firm": "Fees are fixed for the Initial Term. Any increase on renewal is capped at 3% and requires ninety (90) days' notice."
        },
        "acceptance": {"soft": 89, "balanced": 80, "firm": 58}
    }
]

# Legal Risk Knowledge Base for Dynamic Contract Analysis
RISK_RULES = [
    {
        "id": "unlimited_liability",
        "title": "Unlimited Liability",
        "severity": "critical",
        "default_exposure": 50000000,
        "patterns": [
            r"without\s+limit(?:ation)?",
            r"uncapped\s+liability",
            r"unlimited\s+liability",
            r"liable\s+for\s+all\s+losses",
            r"shall\s+be\s+fully\s+liable\s+without\s+cap",
            r"indemnif(?:y|ication)\s+without\s+limitation"
        ],
        "why": "Client bears uncapped liability for potential breaches, data loss, or third-party claims. A single incident could bankrupt or heavily penalize the client beyond the total contract value.",
        "redlines": {
            "soft": "Each party's aggregate liability under this agreement shall be capped at three (3) times the annual fees paid.",
            "balanced": "Vendor's aggregate liability under this Agreement shall not exceed the total fees paid by Client in the twelve (12) months preceding the claim.",
            "firm": "Vendor's aggregate liability shall not exceed fees paid in the 12 months preceding the claim, excluding claims arising from Vendor's gross negligence, data breach, or willful misconduct, which shall remain uncapped."
        },
        "acceptance": {"soft": 88, "balanced": 72, "firm": 46}
    },
    {
        "id": "auto_renewal",
        "title": "Auto-Renewal Trap",
        "severity": "high",
        "default_exposure": 3840000,
        "patterns": [
            r"automatic(?:ally)?\s+renew",
            r"auto-renew",
            r"successive\s+(?:three|two|3|2|\d+)\s+year",
            r"renew\s+unless.*(?:60|90|120)\s+days",
            r"prior\s+written\s+notice\s+of\s+non-renewal"
        ],
        "why": "Agreement automatically locks the client into multi-year renewals unless cancelled within an aggressive notice window, locking in substantial unwanted recurring spend.",
        "redlines": {
            "soft": "This Agreement shall renew for successive one (1) year terms unless either party gives sixty (60) days' written notice prior to term expiration.",
            "balanced": "This Agreement shall renew for successive one (1) year terms unless either party gives thirty (30) days' written notice, and Vendor shall provide a written reminder 60 days before expiration.",
            "firm": "This Agreement shall not renew automatically. Any renewal requires mutual written agreement executed by both parties at least thirty (30) days prior to expiry."
        },
        "acceptance": {"soft": 91, "balanced": 78, "firm": 52}
    },
    {
        "id": "price_escalation",
        "title": "Uncapped Price Escalation",
        "severity": "high",
        "default_exposure": 1200000,
        "patterns": [
            r"revise.*(?:fees|prices|rates)",
            r"increase.*(?:fees|prices|rates)",
            r"at\s+any\s+time.*(?:fees|prices)",
            r"vendor\s+may\s+adjust\s+pricing",
            r"upon\s+(?:7|14|30)\s+days['\s]+notice.*revise"
        ],
        "why": "Vendor reserves the unilateral right to raise service fees on short notice without an annual ceiling or client approval right.",
        "redlines": {
            "soft": "Vendor may revise Fees once per contract year upon sixty (60) days' advance notice, not to exceed 8% annually.",
            "balanced": "Vendor may revise Fees once per contract year with sixty (60) days' advance written notice, capped at the lower of 4% or the Consumer Price Index (CPI).",
            "firm": "Fees are fixed for the Initial Term. Any price adjustment upon renewal is capped at 3% and requires Client's prior written confirmation."
        },
        "acceptance": {"soft": 89, "balanced": 80, "firm": 58}
    },
    {
        "id": "ip_ownership",
        "title": "Intellectual Property Ownership",
        "severity": "medium",
        "default_exposure": 2500000,
        "patterns": [
            r"intellectual\s+property.*belong(?:s)?\s+(?:solely\s+)?to\s+vendor",
            r"deliverables.*property\s+of\s+vendor",
            r"vendor\s+retains\s+all\s+(?:rights|ownership).*deliverable",
            r"work\s+product.*sole\s+property\s+of\s+vendor",
            r"client\s+assigns\s+all\s+rights"
        ],
        "why": "All intellectual property and custom deliverables created under this contract transfer to the vendor, despite being fully funded and commissioned by the client.",
        "redlines": {
            "soft": "All deliverables developed specifically for Client shall be owned by Client, while Vendor retains its pre-existing background tools and IP.",
            "balanced": "Client owns all bespoke deliverables and work product upon payment of fees. Vendor retains pre-existing tools and grants an irrevocable license.",
            "firm": "Client shall retain exclusive, worldwide ownership of all work product, source code, data, and deliverables developed during this engagement."
        },
        "acceptance": {"soft": 85, "balanced": 70, "firm": 40}
    },
    {
        "id": "one_sided_indemnity",
        "title": "One-Sided Indemnification",
        "severity": "high",
        "default_exposure": 3500000,
        "patterns": [
            r"client\s+shall\s+indemnify",
            r"customer\s+shall\s+defend.*vendor",
            r"hold\s+harmless\s+vendor\s+from\s+any",
            r"solely\s+responsible\s+for\s+any\s+third-party\s+claims"
        ],
        "why": "Client is forced to defend and hold vendor harmless from third-party lawsuits without equal, reciprocal protection from the vendor for its service defects.",
        "redlines": {
            "soft": "Client's indemnity obligations shall be reciprocal and mirrored equally by Vendor for service defects.",
            "balanced": "Each party shall mutually defend and indemnify the other solely against third-party claims arising from gross negligence or material breach.",
            "firm": "Mutual indemnification strictly limited to direct third-party intellectual property infringement or data protection violations."
        },
        "acceptance": {"soft": 82, "balanced": 74, "firm": 48}
    },
    {
        "id": "non_refundable_lockin",
        "title": "Unfair Non-Refundable Lock-In",
        "severity": "medium",
        "default_exposure": 1800000,
        "patterns": [
            r"non-refundable",
            r"no\s+refunds?\s+shall\s+be\s+issued",
            r"all\s+fees\s+paid\s+are\s+final",
            r"pay\s+all\s+remaining\s+fees.*termination"
        ],
        "why": "Vendor retains all prepaid fees even if the service is terminated early due to vendor performance issues or convenience.",
        "redlines": {
            "soft": "Upon termination, prepaid fees for unperformed services shall be refunded on a pro-rata basis within 30 days.",
            "balanced": "In the event of early termination without cause, Vendor shall provide a pro-rata refund of all prepaid, unearned fees.",
            "firm": "Client may terminate for convenience with 30 days' notice and receive an immediate 100% pro-rata refund of unspent fees."
        },
        "acceptance": {"soft": 86, "balanced": 75, "firm": 50}
    },
    {
        "id": "governing_law",
        "title": "Foreign Jurisdiction Trap",
        "severity": "low",
        "default_exposure": 950000,
        "patterns": [
            r"exclusive\s+jurisdiction\s+of\s+the\s+courts\s+of",
            r"governed\s+by\s+the\s+laws\s+of\s+(?:delaware|california|new\s+york|england)",
            r"waives\s+any\s+right\s+to\s+jury\s+trial",
            r"class\s+action\s+waiver"
        ],
        "why": "Litigation or disputes are forced into a distant foreign jurisdiction, inflating legal costs exponentially in case of conflict.",
        "redlines": {
            "soft": "Disputes shall be settled through mutually agreed online commercial arbitration.",
            "balanced": "Parties shall submit to good-faith mediation before neutral arbitration in a mutually agreed jurisdiction.",
            "firm": "This Agreement shall be governed solely by the laws and competent courts of Client's principal place of business."
        },
        "acceptance": {"soft": 90, "balanced": 82, "firm": 64}
    }
]

def extract_text_from_file(content: bytes, filename: str) -> str:
    """
    Extracts complete text from PDF or TXT bytes using pypdf, with robust stream decompressor fallbacks.
    """
    if filename.lower().endswith(".txt"):
        return content.decode("utf-8", errors="ignore")

    # 1. Primary: Use pypdf for complete page-by-page extraction
    if HAS_PYPDF:
        try:
            reader = PdfReader(io.BytesIO(content))
            pages_text = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            combined = "\n\n".join(pages_text).strip()
            if len(combined) > 20:
                return combined
        except Exception as e:
            print("pypdf extraction notice:", e)

    # 2. Secondary fallback: zlib stream decompression
    try:
        stream_matches = re.findall(rb'stream[\r\n]+(.*?)[\r\n]+endstream', content, re.DOTALL)
        decompressed_parts = []
        for sm in stream_matches:
            try:
                dec = zlib.decompress(sm)
                matches = re.findall(rb'\((.*?)\)\s*(?:Tj|TJ|\')', dec)
                if matches:
                    decompressed_parts.append(" ".join(m.decode("utf-8", errors="ignore") for m in matches))
            except Exception:
                continue
        if decompressed_parts:
            return "\n\n".join(decompressed_parts)
    except Exception:
        pass

    # 3. Tertiary fallback: printable characters
    cleaned = "".join([chr(b) for b in content if 32 <= b <= 126 or b in (10, 13)])
    return cleaned

def extract_clause_identifier(paragraph: str, fallback_idx: int) -> str:
    """
    Extracts the clause number (e.g., '3.1', '14.2', 'Section 8') from the text.
    """
    # Look for Section/Clause/Article followed by numbers
    m = re.search(r'(?:section|clause|article|para(?:graph)?)\s*([0-9]+(?:\.[0-9]+)*)', paragraph, re.I)
    if m:
        return m.group(1)
    # Look for leading numbers like '9.2' or '4.'
    m = re.search(r'^\s*([0-9]+(?:\.[0-9]+)*)', paragraph)
    if m:
        return m.group(1).rstrip('.')
    return f"{fallback_idx + 1}.0"

def analyze_document_content(text: str) -> List[Dict[str, Any]]:
    """
    Scans the document paragraphs for legal risk patterns and extracts the EXACT
    matching sentences, clause numbers, and dynamic recommendations.
    """
    findings = []
    # Segment into paragraphs and clauses
    raw_paragraphs = re.split(r'\n{2,}|\n(?=[0-9]+\.|\bSection\b|\bClause\b|\bArticle\b)', text)
    paragraphs = [p.strip() for p in raw_paragraphs if len(p.strip()) > 20]

    detected_rules = set()

    for idx, para in enumerate(paragraphs):
        para_clean = " ".join(para.split())
        
        for rule in RISK_RULES:
            if rule["id"] in detected_rules:
                continue
                
            for pattern in rule["patterns"]:
                match = re.search(pattern, para_clean, re.I)
                if match:
                    detected_rules.add(rule["id"])
                    clause_num = extract_clause_identifier(para_clean, len(findings))
                    
                    # Extract the exact sentence around the match for maximum precision
                    sentences = re.split(r'(?<=[.!?])\s+', para_clean)
                    matched_sentence = para_clean
                    for sent in sentences:
                        if re.search(pattern, sent, re.I):
                            matched_sentence = sent.strip()
                            break
                    if len(matched_sentence) > 300:
                        matched_sentence = matched_sentence[:297] + "..."
                        
                    findings.append({
                        "title": rule["title"],
                        "clause": clause_num,
                        "severity": rule["severity"],
                        "exposure_inr": rule["default_exposure"],
                        "why": rule["why"],
                        "original": matched_sentence,
                        "redlines": rule["redlines"],
                        "acceptance": rule["acceptance"]
                    })
                    break

    return findings

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_contract(
    file: Optional[UploadFile] = File(None),
    posture: Optional[str] = Form("balanced"),
    is_sample: Optional[bool] = Form(False)
):
    """
    Analyzes an uploaded contract PDF or runs the built-in Master Services Agreement demo.
    Extracts the actual clauses and sentences from the uploaded file and generates customized redlines.
    """
    try:
        findings = []

        # 1. If user clicked the Sample Demo button or explicit sample request
        if is_sample or (file is None and not is_sample):
            findings = list(SAMPLE_FINDINGS_POOL)
        else:
            filename = getattr(file, "filename", "") or ""
            filename_lower = filename.lower()
            if not (filename_lower.endswith('.pdf') or filename_lower.endswith('.txt')):
                raise HTTPException(status_code=400, detail="Only PDF or TXT contract files are supported.")

            content = await file.read()
            text = extract_text_from_file(content, filename)
            
            if not text or len(text.strip()) < 10:
                raise HTTPException(status_code=400, detail="Could not extract readable text from this document. Please ensure the PDF contains text.")

            findings = analyze_document_content(text)

            # If clean contract (no critical traps detected)
            if not findings:
                findings = [{
                    "title": "Standard Commercial Terms (Low Risk)",
                    "clause": "1.0",
                    "severity": "low",
                    "exposure_inr": 250000,
                    "why": "No severe legal traps (unlimited liability, silent renewals, or uncapped escalations) were detected in this document. Commercial terms appear relatively standard.",
                    "original": text[:200] + ("..." if len(text) > 200 else ""),
                    "redlines": {
                        "soft": "Standard terms accepted with standard commercial verification.",
                        "balanced": "Include standard 30-day notice for convenience and mutual confidentiality.",
                        "firm": "Ensure mutual warranties for intellectual property compliance and data protection."
                    },
                    "acceptance": {"soft": 98, "balanced": 94, "firm": 85}
                }]

        total_exposure = sum(f["exposure_inr"] for f in findings)

        # Dynamic risk reduction by negotiation posture
        reduction_multiplier = {
            "soft": 0.05,
            "balanced": 0.015,
            "firm": 0.005
        }.get(posture, 0.015)

        exposure_after = int(total_exposure * reduction_multiplier)
        
        # Calculate dynamic risk score based on severity and count
        severity_points = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        calculated_score = sum(severity_points.get(f["severity"], 2) for f in findings)
        risk_score = min(max(calculated_score, 2), 10)

        return {
            "risk_score": risk_score,
            "total_exposure_inr": total_exposure,
            "exposure_after_inr": exposure_after,
            "findings": findings
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing contract: {str(e)}")

# Frontend Static File Serving
@app.get("/")
async def serve_index():
    index_path = BASE_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "index.html not found"}

@app.get("/style.css")
async def serve_css():
    css_path = BASE_DIR / "style.css"
    if css_path.exists():
        return FileResponse(css_path, media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/script.js")
async def serve_js():
    js_path = BASE_DIR / "script.js"
    if js_path.exists():
        return FileResponse(js_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="script.js not found")

@app.get("/api/status")
def read_status():
    return {
        "status": "online",
        "service": "VendorGuard AI Engine (Dynamic v2)",
        "pypdf_enabled": HAS_PYPDF,
        "documentation": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
