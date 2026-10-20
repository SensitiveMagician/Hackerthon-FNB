import json, os, secrets, logging
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, text
from pydantic import BaseModel, EmailStr, Field
from .database import Base, engine, get_db
from .models import User, Profile, BusinessPlan, TransactionRecord, TransactionAudit, SupplierListing, BusinessOrder, FounderDocument
from .security import hash_password, verify_password, create_token, read_token, token_hash
from .mailer import send_verification
from .plan import build_plan
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from io import BytesIO

load_dotenv()
logging.basicConfig(level=logging.INFO)
BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="MALI MODE", description="Youth entrepreneurship and small-business growth platform")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
Base.metadata.create_all(bind=engine)
ROLES = {"business_owner", "new_entrepreneur", "supplier", "delivery_partner"}

class TransactionInput(BaseModel):
    transaction_date: str = Field(min_length=10, max_length=10)
    transaction_type: str
    description: str = Field(min_length=1, max_length=240)
    category: str = Field(default="Other", max_length=60)
    amount: float = Field(gt=0, le=100000000)
    quantity: float = Field(default=1, gt=0, le=10000000)
    payment_method: str = Field(default="Other", max_length=40)
    source: str = Field(default="typed", max_length=20)

class TransactionParseInput(BaseModel):
    text: str = Field(min_length=2, max_length=2000)

class TransactionUpdateInput(BaseModel):
    transaction_date: str = Field(min_length=10, max_length=10)
    transaction_type: str
    description: str = Field(min_length=1, max_length=240)
    category: str = Field(default="Other", max_length=60)
    amount: float = Field(gt=0, le=100000000)
    quantity: float = Field(default=1, gt=0, le=10000000)
    payment_method: str = Field(default="Other", max_length=40)

class TransactionConfirmInput(BaseModel):
    rows: list[dict]
    source: str = "typed"
    raw_input: str | None = None

class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    role: str
    password: str = Field(min_length=10, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=40)
    location: str = Field(min_length=2, max_length=180)
    business_name: str = Field(min_length=2, max_length=180)
    business_type: str = Field(min_length=2, max_length=120)
    product_service: str = Field(default="Not provided", max_length=500)
    target_customers: str = Field(default="Not provided", max_length=500)
    customer_problem: str = Field(default="Not provided", max_length=1000)
    starting_budget: float = Field(default=0, ge=0)
    selling_price: float = Field(default=0, ge=0)
    unit_cost: float = Field(default=0, ge=0)
    expected_units_month: int = Field(default=0, ge=0)
    monthly_fixed_costs: float = Field(default=0, ge=0)
    funding_needed: float = Field(default=0, ge=0)
    marketing_plan: str = Field(default="Not provided", max_length=1000)
    operations: str = Field(default="Not provided", max_length=1000)
    risks: str = Field(default="Not provided", max_length=1000)
    registration_status: str = Field(default="Not sure what is required", max_length=80)
    experience: str = Field(default="Not provided", max_length=1000)
    role_details: str = Field(default="", max_length=1500)


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("mali_mode_session")
    uid = read_token(token) if token else None
    if not uid: raise HTTPException(status_code=401, detail="Please sign in again.")
    user = db.get(User, uid)
    if not user or not user.is_active: raise HTTPException(status_code=401, detail="Account not available.")
    return user

def profile_data(db, user):
    p = db.scalar(select(Profile).where(Profile.user_id == user.id))
    return p, (json.loads(p.data_json) if p else {})

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/health")
def health():
    # Render uses this endpoint to confirm the app and configured database are reachable.
    from sqlalchemy.exc import SQLAlchemyError
    from fastapi.responses import JSONResponse
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "app": "MALI MODE", "mode": "hackathon_mvp", "database": "connected"}
    except SQLAlchemyError:
        logging.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "app": "MALI MODE", "database": "unavailable"},
        )

@app.post("/api/signup")
def signup(data: SignupIn, db: Session = Depends(get_db)):
    if data.role not in ROLES: raise HTTPException(422, "Choose a valid account type.")
    if db.scalar(select(User).where(User.email == data.email.lower())): raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    if len(data.password) < 10 or not any(c.isalpha() for c in data.password) or not any(c.isdigit() for c in data.password): raise HTTPException(422, "Use at least 10 characters, including a letter and a number.")
    token = secrets.token_urlsafe(32)
    user = User(full_name=data.full_name.strip(), email=data.email.lower(), phone=data.phone.strip(), role=data.role, password_hash=hash_password(data.password), verification_token_hash=token_hash(token))
    db.add(user); db.commit(); db.refresh(user)
    db.add(Profile(user_id=user.id, data_json=json.dumps({"full_name":user.full_name,"phone":user.phone,"email":user.email}), completed=False)); db.commit()
    try: send_verification(user.email, user.full_name, token)
    except Exception: logging.exception("Verification email failed")
    return {"message":"Account created. Verify your email before signing in.", "email":user.email, "verification_sent":bool(os.getenv("SMTP_HOST"))}

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.verification_token_hash == token_hash(token)))
    if not user: return HTMLResponse("<h2>This verification link is invalid or has already been used.</h2><p>Please request a new verification email.</p>", status_code=400)
    user.email_verified = True; user.verification_token_hash = None; db.commit()
    return templates.TemplateResponse(request, "verified.html", {"email":user.email})

@app.post("/api/login")
def login(data: LoginIn, response=None, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash): raise HTTPException(401, "Email or password is incorrect.")
    if not user.email_verified: raise HTTPException(403, "Please verify your email using the link sent to you before signing in.")
    token = create_token(user.id)
    result = JSONResponse({"message":"Signed in.", "user":{"id":user.id,"name":user.full_name,"role":user.role,"email":user.email}})
    result.set_cookie("mali_mode_session", token, httponly=True, secure=os.getenv("COOKIE_SECURE", "false").lower()=="true", samesite="lax", max_age=43200, path="/")
    return result

@app.post("/api/logout")
def logout():
    r = JSONResponse({"message":"Signed out."}); r.delete_cookie("mali_mode_session", path="/"); return r

@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, data = profile_data(db, user)
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.user_id == user.id))
    gate_complete = user.role != "new_entrepreneur" or bool(p and p.completed and plan)
    return {"id":user.id,"name":user.full_name,"email":user.email,"phone":user.phone,"role":user.role,"email_verified":user.email_verified,"profile_completed":bool(p and p.completed),"business_plan_ready":bool(plan),"dashboard_unlocked":gate_complete,"profile":data}

@app.post("/api/profile")
def save_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Entrepreneurs must provide the full planning profile before the dashboard is unlocked.
    if user.role == "new_entrepreneur":
        if data.starting_budget <= 0: raise HTTPException(422, "Enter a starting budget above zero. If you have no starting capital, explain a realistic funding plan before continuing.")
        if data.selling_price < data.unit_cost and data.expected_units_month > 0: raise HTTPException(422, "Your selling price is below your unit cost. Review your numbers or explain your pricing strategy before continuing.")
    elif not data.role_details.strip():
        raise HTTPException(422, "Please complete the details requested for your account type.")
    p = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not p: p = Profile(user_id=user.id, data_json="{}", completed=False); db.add(p)
    d = data.model_dump(); d["email"] = user.email; d["role"] = user.role
    p.data_json = json.dumps(d); p.completed = True
    user.full_name = data.full_name.strip(); user.phone = data.phone.strip()
    db.commit()
    return {"message":"Profile saved.", "profile_completed":True}

@app.post("/api/business-plan/generate")
def generate_plan(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "new_entrepreneur": raise HTTPException(403, "The guided startup plan is for new entrepreneurs.")
    p, data = profile_data(db, user)
    if not p or not p.completed: raise HTTPException(403, "Complete your full business profile before generating a plan.")
    plan_data = build_plan(data)
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.user_id == user.id))
    if not plan: plan = BusinessPlan(user_id=user.id, plan_json=json.dumps(plan_data)); db.add(plan)
    else: plan.plan_json = json.dumps(plan_data)
    db.commit()
    return {"message":"Business plan generated from your answers. Review every section before using it.", "plan":plan_data,"dashboard_unlocked":True}

@app.get("/api/business-plan")
def get_plan(user: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.user_id == user.id))
    if not plan: raise HTTPException(404, "Complete the guided profile and generate your plan first.")
    return json.loads(plan.plan_json)

@app.get("/api/business-plan.pdf")
def download_plan(user: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.user_id == user.id))
    if not plan: raise HTTPException(403, "Generate your business plan before downloading it.")
    d = json.loads(plan.plan_json); buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=48,leftMargin=48,topMargin=48,bottomMargin=48)
    styles = getSampleStyleSheet(); styles.add(ParagraphStyle(name="KasiTitle", parent=styles["Title"], textColor=colors.HexColor("#145b43"), spaceAfter=16))
    story = [Paragraph(d["title"], styles["KasiTitle"]), Paragraph(f"Prepared {d['created']} • Draft based on owner-provided information", styles["Normal"]), Spacer(1,14)]
    sections = [("Executive summary","executive_summary"),("Product or service","offer"),("Target customers","customers"),("Operating area","area"),("Customer need","customer_problem"),("Marketing plan","marketing"),("Operations","operations"),("Starting budget","budget"),("Funding sought","funding_needed"),("Pricing and assumptions","financial_note"),("Risk considerations","risks")]
    for heading,key in sections:
        story.extend([Paragraph(heading, styles["Heading2"]), Paragraph(str(d.get(key,"Not provided")).replace("&","&amp;"), styles["BodyText"]), Spacer(1,6)])
    story.append(Paragraph("Illustrative monthly estimate", styles["Heading2"]))
    for label,key in [("Expected units/month","monthly_units"),("Estimated revenue","monthly_revenue"),("Estimated variable costs","monthly_variable_cost"),("Monthly fixed costs","monthly_fixed_costs"),("Estimated surplus before omitted costs","estimated_monthly_surplus")]: story.append(Paragraph(f"{label}: {d.get(key,'Not provided')}", styles["BodyText"]))
    story.append(Paragraph("Milestones", styles["Heading2"]))
    story.append(ListFlowable([ListItem(Paragraph(x,styles["BodyText"])) for x in d["milestones"]], bulletType="bullet"))
    story.append(Paragraph("Documentation checklist", styles["Heading2"]))
    story.append(ListFlowable([ListItem(Paragraph(x,styles["BodyText"])) for x in d["documents"]], bulletType="bullet"))
    story.extend([Spacer(1,12), Paragraph(d["disclaimer"], styles["Italic"])])
    doc.build(story); buf.seek(0)
    filename = "MALI_MODE_Business_Plan.pdf"
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition":f'attachment; filename="{filename}"'})

def _tx_json(row):
    if not row: return None
    return {"id":row.id,"transaction_date":row.transaction_date,"transaction_type":row.transaction_type,"description":row.description,"category":row.category,"amount":row.amount/100,"quantity":float(row.quantity or 1),"payment_method":row.payment_method,"source":row.source}

def _tx_audit(db, user_id, action, transaction_id=None, raw_input=None, before=None, after=None):
    db.add(TransactionAudit(user_id=user_id, transaction_id=transaction_id, action=action, raw_input=(raw_input or "")[:4000] or None, before_json=json.dumps(before, ensure_ascii=False) if before else None, after_json=json.dumps(after, ensure_ascii=False) if after else None))

def _duplicate(db, user_id, values, exclude_id=None):
    # Strict duplicate guard: same owner/date/type/amount and normalized description.
    q=select(TransactionRecord).where(TransactionRecord.user_id==user_id, TransactionRecord.transaction_date==values["transaction_date"], TransactionRecord.transaction_type==values["transaction_type"], TransactionRecord.amount==round(float(values["amount"])*100))
    if exclude_id is not None: q=q.where(TransactionRecord.id != exclude_id)
    import re
    from difflib import SequenceMatcher
    norm=lambda x: re.sub(r"[^a-z0-9]+", " ", str(x or "").lower()).strip()
    target=norm(values.get("description"))
    for existing in db.scalars(q).all():
        candidate=norm(existing.description)
        # Exact normalized match or very similar wording on same date/type/amount.
        if candidate==target or (target and candidate and SequenceMatcher(None,candidate,target).ratio() >= 0.88):
            return existing
    return None

def _validated_tx(values):
    kind=str(values.get("transaction_type", "Sale"))
    if kind not in {"Sale","Purchase","Expense","Refund"}: raise HTTPException(422,"Choose a valid transaction type.")
    pay=str(values.get("payment_method","Other"))
    if pay not in {"Cash","Card","Bank Transfer","E-wallet","Credit","Other"}: raise HTTPException(422,"Choose a valid payment method.")
    try: parsed=date.fromisoformat(str(values.get("transaction_date", "")))
    except ValueError: raise HTTPException(422,"Use a valid transaction date.")
    if parsed>date.today(): raise HTTPException(422,"Transaction date cannot be in the future.")
    desc=str(values.get("description", "")).strip()
    amount=float(values.get("amount", 0)); qty=float(values.get("quantity",1))
    if not desc or amount<=0 or qty<=0: raise HTTPException(422,"Enter a description, positive amount and positive quantity.")
    return {"transaction_date":parsed.isoformat(),"transaction_type":kind,"description":desc[:240],"category":str(values.get("category","Other"))[:60],"amount":amount,"quantity":qty,"payment_method":pay}

def parse_transaction_text(raw: str):
    """Conservative rule-based parser for the hackathon MVP; user must review its draft."""
    import re
    text = raw.strip()
    low = text.lower()
    if re.search(r'\b(sold|sale|selling|received payment)\b', low): kind = "Sale"
    elif re.search(r'\b(bought|buy|purchase|purchased|restocked)\b', low): kind = "Purchase"
    elif re.search(r'\b(refund|refunded|returned money)\b', low): kind = "Refund"
    elif re.search(r'\b(spent|paid|expense|cost me|fuel|transport|rent|electricity|wages)\b', low): kind = "Expense"
    else: kind = "Sale"
    patterns = [r'\bR\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)', r'\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:rand|rands|zar)\b', r'\b(?:for|of|amount(?:ing)? to|paid)\s+(?:R\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)']
    amount = None
    for pat in patterns:
        m = re.search(pat, low, re.I)
        if m:
            try: amount = float(m.group(1).replace(',', '')); break
            except ValueError: pass
    qty = 1.0
    m = re.search(r'\b([0-9]+(?:\.[0-9]+)?)\s+(?:bags?|bunches?|boxes?|crates?|bottles?|packs?|kg|kilograms?|units?|items?)\b', low)
    if m: qty = float(m.group(1))
    pay = "Cash" if re.search(r'\b(cash)\b', low) else "Card" if re.search(r'\b(card|swipe)\b', low) else "Bank Transfer" if re.search(r'\b(bank transfer|eft|transfer)\b', low) else "E-wallet" if re.search(r'\b(e-wallet|ewallet|mobile money)\b', low) else "Other"
    category = "Stock" if kind == "Purchase" else "Transport" if re.search(r'\b(transport|taxi|fuel|petrol)\b', low) else "Sales" if kind == "Sale" else "Other"
    cleaned = re.sub(r'\b(today|yesterday|this morning|tonight|cash|by card|card|bank transfer|eft|transfer|e-wallet|ewallet|mobile money|sold|sell|selling|bought|buy|purchased|purchase|restocked|spent|paid|expense|refunded|refund|received payment for)\b', '', text, flags=re.I)
    cleaned = re.sub(r'\bR\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?\b|\b[0-9][0-9,]*(?:\.[0-9]{1,2})?\s*(?:rand|rands|zar)\b', '', cleaned, flags=re.I)
    cleaned = re.sub(r'^I\s+', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\b(for|of)\s*$', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' .,!;:-') or text
    txdate = date.today() - timedelta(days=1) if re.search(r'\byesterday\b', low) else date.today()
    return {"transaction_date":txdate.isoformat(), "transaction_type":kind, "description":cleaned[:240], "category":category, "amount":amount, "quantity":qty, "payment_method":pay, "source":"typed", "needs_review":True, "original_text":text}

@app.post("/api/transactions/parse")
def transaction_parse(data: TransactionParseInput, user: User = Depends(current_user)):
    # Split simple multi-event notes into reviewable drafts; nothing is saved until confirmed.
    import re
    chunks=[x.strip() for x in re.split(r"(?<=[.!?])\s+(?=(?:I |We |Today |Yesterday |The client |Customer ))", data.text.strip()) if x.strip()]
    if len(chunks)>1:
        drafts=[]
        for chunk in chunks[:20]:
            draft=parse_transaction_text(chunk); draft["original_text"]=data.text; drafts.append(draft)
        return {"multiple":True,"original_text":data.text,"drafts":drafts}
    result=parse_transaction_text(data.text); result["original_text"]=data.text
    return result

@app.get("/api/transactions")
def list_transactions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(TransactionRecord).where(TransactionRecord.user_id == user.id).order_by(desc(TransactionRecord.id)).limit(300)).all()
    return [_tx_json(r) for r in rows]

@app.get("/api/business-insights")
def business_insights(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Transparent rule-based insights calculated only from the signed-in user's saved records."""
    from collections import Counter, defaultdict
    from datetime import datetime
    rows = db.scalars(select(TransactionRecord).where(TransactionRecord.user_id == user.id).order_by(TransactionRecord.transaction_date.asc()).limit(5000)).all()
    tx = []
    for r in rows:
        try:
            tx.append({"date": date.fromisoformat(r.transaction_date), "type": r.transaction_type,
                       "description": (r.description or "Unlabelled transaction").strip(),
                       "category": (r.category or "Other").strip(), "amount": r.amount / 100,
                       "quantity": float(r.quantity or 1)})
        except (ValueError, TypeError):
            continue
    today = date.today()
    current_start = today - timedelta(days=29)
    previous_start = today - timedelta(days=59)
    sales_types = {"Sale"}
    cost_types = {"Purchase", "Expense"}
    current = [r for r in tx if current_start <= r["date"] <= today]
    previous = [r for r in tx if previous_start <= r["date"] < current_start]
    def totals(items):
        sales = sum(r["amount"] for r in items if r["type"] in sales_types)
        refunds = sum(r["amount"] for r in items if r["type"] == "Refund")
        costs = sum(r["amount"] for r in items if r["type"] in cost_types)
        return {"sales": round(sales, 2), "refunds": round(refunds, 2), "costs": round(costs, 2), "net_recorded": round(sales - refunds - costs, 2)}
    cur, prev = totals(current), totals(previous)
    advice = []
    if len(tx) < 5:
        advice.append({"title":"Build a useful record history", "priority":"Start here", "detail":f"You have {len(tx)} saved transaction(s). Record sales and costs consistently for at least a few weeks before relying on trends. You can import old records to get started faster."})
    if cur["sales"] > 0 and cur["costs"] > cur["sales"] - cur["refunds"]:
        advice.append({"title":"Costs are higher than recorded sales", "priority":"High", "detail":"In the last 30 days, recorded purchases and expenses exceed sales after refunds. Review your largest costs and confirm that all sales have been recorded. This is a record-based warning, not a full accounting profit calculation."})
    elif cur["sales"] > 0 and cur["net_recorded"] >= 0:
        advice.append({"title":"Keep tracking the money left over", "priority":"Useful next step", "detail":f"Your recorded sales less purchases, expenses and refunds are R{cur['net_recorded']:.2f} for the last 30 days. Keep recording every cost, including transport and fees, to make this estimate more complete."})
    if prev["sales"] > 0:
        change = ((cur["sales"] - prev["sales"]) / prev["sales"]) * 100
        if change <= -15:
            advice.append({"title":"Recorded sales have fallen", "priority":"Review", "detail":f"Sales are {abs(change):.0f}% lower than the previous 30-day period. Check your sales days, product availability and customer activity before deciding what to change."})
        elif change >= 15:
            advice.append({"title":"Recorded sales are growing", "priority":"Opportunity", "detail":f"Sales are {change:.0f}% higher than the previous 30-day period. Check that stock and supplier capacity can keep up, and avoid increasing costs until the trend is sustained."})
    category_costs = defaultdict(float)
    for r in current:
        if r["type"] in cost_types:
            category_costs[r["category"] or "Other"] += r["amount"]
    if category_costs:
        top_cat, top_value = max(category_costs.items(), key=lambda kv: kv[1])
        advice.append({"title":"Review your largest recorded cost", "priority":"Cost control", "detail":f"{top_cat} is your largest purchase/expense category in the last 30 days at R{top_value:.2f}. Compare prices or quantities with your records before making a change."})
    sale_descriptions = Counter(r["description"] for r in current if r["type"] == "Sale" and r["description"])
    if sale_descriptions:
        top_item, count = sale_descriptions.most_common(1)[0]
        advice.append({"title":"Look at repeat sales", "priority":"Sales insight", "detail":f'"{top_item}" appears in {count} recorded sale(s) in the last 30 days. Check whether this reflects repeat demand and whether you have enough stock.'})
    if not tx:
        advice = [{"title":"Start with one real transaction", "priority":"First step", "detail":"Record a sale or expense, or import your existing records. MALI MODE will use your saved history to calculate business indicators and give record-based suggestions."}]
    # Product-level movement estimates are inferred from descriptions and quantities entered by the owner.
    products = {}
    for r in tx:
        key = " ".join((r["description"] or "").lower().split())
        if not key: continue
        item=products.setdefault(key,{"item":r["description"],"sold_qty":0.0,"bought_qty":0.0,"sales_value":0.0,"sale_count":0,"last_sale":None})
        if r["type"]=="Sale": item["sold_qty"]+=r["quantity"]; item["sales_value"]+=r["amount"]; item["sale_count"]+=1; item["last_sale"]=r["date"].isoformat()
        elif r["type"]=="Purchase": item["bought_qty"]+=r["quantity"]
    product_rows=sorted(products.values(),key=lambda x:(x["sold_qty"],x["sales_value"]),reverse=True)
    stock_recommendations=[]
    for item in product_rows[:10]:
        balance=max(0,item["bought_qty"]-item["sold_qty"])
        if item["sold_qty"]>0:
            stock_recommendations.append({"item":item["item"],"sold_quantity":round(item["sold_qty"],2),"purchased_quantity":round(item["bought_qty"],2),"estimated_recorded_balance":round(balance,2),"sales_value":round(item["sales_value"],2),"sales_count":item["sale_count"],"recommendation":("Fast-moving in recorded sales; check remaining stock and supplier lead time." if item["sold_qty"]>=max(3, item["bought_qty"]*0.7) else "Selling in recorded data; monitor before restocking heavily.")})
    # Use a real hosted language model when configured. The prompt contains aggregate business records only.
    ai_used=False; ai_error=None
    api_key=os.getenv("OPENAI_API_KEY")
    if api_key and tx:
        try:
            import urllib.request
            model=os.getenv("OPENAI_MODEL","gpt-4o-mini")
            summary={"record_count":len(tx),"current_30_days":cur,"previous_30_days":prev,"product_performance":product_rows[:15],"category_costs":dict(category_costs)}
            prompt="You are a cautious small-business analyst. Use only supplied saved-record data. Return JSON object with advice array of objects title, priority, detail and stock_recommendations array of objects item, recommendation. Explain data gaps. Never invent stock-on-hand, customer preferences, profit, or trends not supported by data. If there are no customer ratings/feedback, say customer preferences cannot be established from sales alone. Keep advice practical and plain-language. Data: "+json.dumps(summary, default=str)
            payload=json.dumps({"model":model,"messages":[{"role":"system","content":"Analyse small business transaction data conservatively. Output valid JSON only."},{"role":"user","content":prompt}],"response_format":{"type":"json_object"},"temperature":0.2}).encode()
            req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=payload,headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(req,timeout=18) as resp: result=json.loads(resp.read().decode())
            parsed=json.loads(result["choices"][0]["message"]["content"])
            if isinstance(parsed.get("advice"),list) and parsed["advice"]: advice=parsed["advice"][:8]
            if isinstance(parsed.get("stock_recommendations"),list) and parsed["stock_recommendations"]: stock_recommendations=parsed["stock_recommendations"][:10]
            ai_used=True
        except Exception as exc:
            logging.warning("AI insights unavailable; using deterministic analysis: %s", exc.__class__.__name__); ai_error="AI service unavailable; showing data-derived fallback insights."
    method=(f"AI model analysis ({os.getenv('OPENAI_MODEL','gpt-4o-mini')}) plus saved-record calculations." if ai_used else "Transparent rule-based, data-derived fallback analysis; configure OPENAI_API_KEY to enable live AI-generated explanations.")+" Suggestions are limited by the records entered. Stock balance is an estimate from recorded purchases minus sales, not a physical stock count. Customer preferences cannot be inferred reliably without customer feedback or ratings."
    return {"generated_at": today.isoformat(), "records_analysed": len(tx), "period_days": 30, "current_period": cur, "previous_period": prev, "advice": advice[:8], "stock_recommendations":stock_recommendations, "ai_enabled":bool(api_key), "ai_used":ai_used, "ai_notice":ai_error, "method":method}

@app.post("/api/transactions")
def create_transaction(data: TransactionInput, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    values=_validated_tx(data.model_dump())
    raw_input=request.headers.get("x-mali-raw-input", "")
    duplicate=_duplicate(db,user.id,values)
    if duplicate:
        _tx_audit(db,user.id,"duplicate_blocked",duplicate.id,raw_input=raw_input,after=_tx_json(duplicate)); db.commit()
        raise HTTPException(409,detail=f"Possible duplicate blocked. A matching record already exists (record #{duplicate.id}, {duplicate.transaction_date}, R{duplicate.amount/100:.2f}). Review the existing record instead of saving it again.")
    row=TransactionRecord(user_id=user.id, transaction_date=values["transaction_date"], transaction_type=values["transaction_type"], description=values["description"], category=values["category"], amount=round(values["amount"]*100), quantity=str(values["quantity"]), payment_method=values["payment_method"], source=data.source if data.source in {"typed","voice","scan","csv"} else "typed")
    db.add(row); db.flush(); _tx_audit(db,user.id,"created",row.id,raw_input=raw_input,after=_tx_json(row)); db.commit(); db.refresh(row)
    return {"message":"Record saved successfully.","transaction":_tx_json(row)}

@app.put("/api/transactions/{transaction_id}")
def update_transaction(transaction_id:int,data:TransactionUpdateInput,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.scalar(select(TransactionRecord).where(TransactionRecord.id==transaction_id,TransactionRecord.user_id==user.id))
    if not row: raise HTTPException(404,"Transaction not found.")
    values=_validated_tx(data.model_dump()); duplicate=_duplicate(db,user.id,values,exclude_id=transaction_id)
    if duplicate:
        _tx_audit(db,user.id,"duplicate_blocked",duplicate.id,raw_input=request.headers.get("x-mali-raw-input",""),before=_tx_json(row),after=_tx_json(duplicate)); db.commit()
        raise HTTPException(409,detail=f"Possible duplicate blocked: matching record #{duplicate.id} already exists.")
    before=_tx_json(row)
    for k,v in values.items(): setattr(row,k,round(v*100) if k=="amount" else str(v) if k=="quantity" else v)
    _tx_audit(db,user.id,"updated",row.id,raw_input=request.headers.get("x-mali-raw-input",""),before=before,after=_tx_json(row)); db.commit(); db.refresh(row)
    return {"message":"Record updated successfully.","transaction":_tx_json(row)}

@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.scalar(select(TransactionRecord).where(TransactionRecord.id==transaction_id,TransactionRecord.user_id==user.id))
    if not row: raise HTTPException(404,"Transaction not found or already deleted.")
    before=_tx_json(row); _tx_audit(db,user.id,"deleted",row.id,before=before); db.delete(row); db.commit()
    return {"message":"Record deleted successfully. The deletion was recorded in the audit history.","deleted_id":transaction_id}

@app.get("/api/transactions/audit")
def transaction_audit(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(TransactionAudit).where(TransactionAudit.user_id==user.id).order_by(desc(TransactionAudit.id)).limit(200)).all()
    return [{"id":r.id,"transaction_id":r.transaction_id,"action":r.action,"raw_input":r.raw_input,"before":json.loads(r.before_json) if r.before_json else None,"after":json.loads(r.after_json) if r.after_json else None,"created_at":str(r.created_at)} for r in rows]

@app.post("/api/transactions/scan")
async def scan_records(file: UploadFile = File(...), user: User = Depends(current_user)):
    """Extract text from a photographed page/receipt. OCR is optional and must be installed locally."""
    name = (file.filename or "").lower()
    if not name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        raise HTTPException(415,"Upload a photo (PNG, JPG, WEBP or TIFF). For existing spreadsheets, use CSV import instead.")
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024: raise HTTPException(413,"Image must be smaller than 8 MB.")
    try:
        from PIL import Image
        import pytesseract
        from io import BytesIO as ImageBytes
        img = Image.open(ImageBytes(raw)).convert("RGB")
        extracted = pytesseract.image_to_string(img)
    except ImportError:
        raise HTTPException(503,"Photo scanning needs Pillow, pytesseract and the Tesseract OCR program. Install the optional scan requirements and Tesseract, or use voice/text/CSV import.")
    except Exception:
        raise HTTPException(422,"Could not read this image. Try a clear, well-lit photo taken straight-on.")
    lines = [line.strip(" •\t") for line in extracted.splitlines() if line.strip()]
    parsed=[]
    for line in lines:
        draft=parse_transaction_text(line)
        if draft.get("amount") and draft.get("description"):
            draft["source"]="scan"
            parsed.append({k:draft[k] for k in ["transaction_date","transaction_type","description","category","amount","quantity","payment_method","source"]})
    return {"message":"Text extracted. OCR can misread handwriting, dates and amounts. Review each suggested row before confirming.","extracted_text":"\n".join(lines)[:12000],"lines":lines[:100],"preview":parsed[:100],"source":"scan"}

@app.post("/api/transactions/import-csv")
async def import_transactions_csv(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from io import StringIO
    if not (file.filename or "").lower().endswith(".csv"): raise HTTPException(415,"Please upload a CSV file.")
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024: raise HTTPException(413,"CSV must be smaller than 2 MB.")
    try: rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))
    except Exception: raise HTTPException(422,"Could not read the CSV. Save it as UTF-8 CSV and try again.")
    if not rows: raise HTTPException(422,"The CSV has no data rows.")
    if len(rows)>1000: raise HTTPException(413,"Import up to 1,000 rows at a time.")
    made=[]; errors=[]
    for i,r in enumerate(rows, start=2):
        low={str(k).strip().lower():v for k,v in r.items() if k}
        try:
            amount=float(str(low.get("amount", low.get("amount (r)", low.get("value", "")))).replace("R","").replace(","," ").replace(" ",""))
            kind=str(low.get("type",low.get("transaction_type","Sale"))).strip().title()
            if kind not in {"Sale","Purchase","Expense","Refund"}: kind="Sale"
            desc=str(low.get("description",low.get("item",low.get("item or description","Imported transaction")))).strip()[:240]
            rawdate=str(low.get("date",low.get("transaction_date",date.today().isoformat()))).strip()[:10]
            date.fromisoformat(rawdate)
            if amount<=0 or not desc: raise ValueError("description/amount missing")
            made.append({"transaction_date":rawdate,"transaction_type":kind,"description":desc,"category":str(low.get("category","Other"))[:60],"amount":amount,"quantity":float(low.get("quantity",1) or 1),"payment_method":str(low.get("payment method",low.get("payment_method","Other"))).title()[:40] or "Other"})
        except Exception: errors.append(f"Row {i}: missing/invalid date, description or amount")
    return {"rows_found":len(rows),"valid_count":len(made),"errors":errors[:30],"preview":made[:100],"message":"Preview only. Nothing has been saved yet. Review the rows, then confirm import."}

@app.post("/api/transactions/import-confirm")
def confirm_import(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows=payload.get("rows",[])
    source=payload.get("source", "csv")
    source=source if source in {"csv","scan","typed","voice"} else "csv"
    if not isinstance(rows,list) or not rows or len(rows)>1000: raise HTTPException(422,"Choose between 1 and 1,000 reviewed rows.")
    created=0; skipped=0
    for item in rows:
        try:
            d=date.fromisoformat(str(item["transaction_date"]))
            kind=str(item["transaction_type"])
            amount=float(item["amount"]); qty=float(item.get("quantity",1))
            desc=str(item["description"]).strip()
            if d>date.today() or kind not in {"Sale","Purchase","Expense","Refund"} or amount<=0 or qty<=0 or not desc: continue
            pay=str(item.get("payment_method","Other")); pay=pay if pay in {"Cash","Card","Bank Transfer","E-wallet","Credit","Other"} else "Other"
            values={"transaction_date":d.isoformat(),"transaction_type":kind,"description":desc[:240],"category":str(item.get("category","Other"))[:60],"amount":amount,"quantity":qty,"payment_method":pay}
            if _duplicate(db,user.id,values):
                skipped+=1; continue
            row=TransactionRecord(user_id=user.id,transaction_date=d.isoformat(),transaction_type=kind,description=desc[:240],category=values["category"],amount=round(amount*100),quantity=str(qty),payment_method=pay,source=source); db.add(row); db.flush(); _tx_audit(db,user.id,"created",row.id,raw_input=json.dumps(item,ensure_ascii=False),after=_tx_json(row)); created+=1
        except Exception: continue
    db.commit()
    return {"message":f"Import complete: {created} record(s) saved; {skipped} possible duplicate(s) skipped.","imported":created,"duplicates_skipped":skipped}

@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, data = profile_data(db, user)
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.user_id == user.id))
    if user.role == "new_entrepreneur" and not (p and p.completed and plan):
        raise HTTPException(403, "Your dashboard is locked. Complete the guided profile and generate your business plan first.")
    labels = {"business_owner":"Business owner dashboard", "new_entrepreneur":"Business growth dashboard", "supplier":"Supplier dashboard", "delivery_partner":"Delivery partner dashboard"}
    actions = {
      "business_owner":["Record sales and expenses","Manage stock","Find local suppliers","Prepare business reports and tender documents"],
      "new_entrepreneur":["Review your business plan","Track sales and expenses","Build six-month records","Explore local tenders and formal markets"],
      "supplier":["Manage product catalogue","Review incoming orders","Confirm prices and availability","Contact buyers"],
      "delivery_partner":["View delivery requests","Confirm pickup and drop-off","Share location during delivery","Update delivery status"]}
    return {"title":labels[user.role],"role":user.role,"profile":data,"actions":actions[user.role],"plan_ready":bool(plan)}

# Founder trade, supplier orders and formalisation endpoints.
@app.get("/api/suppliers")
def list_suppliers(category: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(SupplierListing).where(SupplierListing.active == True)
    if category.strip(): q = q.where(SupplierListing.category.ilike(f"%{category.strip()[:80]}%"))
    rows = db.scalars(q.order_by(desc(SupplierListing.id)).limit(200)).all()
    return [{"id":r.id,"supplier_name":r.supplier_name,"category":r.category,"description":r.description,"indicative_price":r.price/100 if r.price is not None else None,"unit":r.unit,"location":r.location,"contact_name":r.contact_name,"contact_email":r.contact_email,"contact_phone":r.contact_phone,"is_mine":r.owner_user_id==user.id} for r in rows]

@app.post("/api/suppliers")
def create_supplier(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    name=str(payload.get("supplier_name","")).strip()[:180]; category=str(payload.get("category","")).strip()[:100]
    if not name or not category: raise HTTPException(422,"Supplier name and category are required.")
    price=payload.get("indicative_price")
    try: price_cents=round(float(price)*100) if price not in (None,"") else None
    except ValueError: raise HTTPException(422,"Price must be a number.")
    if price_cents is not None and price_cents < 0: raise HTTPException(422,"Price cannot be negative.")
    row=SupplierListing(owner_user_id=user.id,supplier_name=name,category=category,description=str(payload.get("description", ""))[:2000],price=price_cents,unit=str(payload.get("unit","unit"))[:60],location=str(payload.get("location",""))[:180],contact_name=str(payload.get("contact_name",""))[:180],contact_email=str(payload.get("contact_email",""))[:255],contact_phone=str(payload.get("contact_phone",""))[:60])
    db.add(row); db.commit(); db.refresh(row)
    return {"message":"Supplier listing saved. Buyers can now send an order request.","id":row.id}

@app.post("/api/orders")
def create_order(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try: supplier_id=int(payload.get("supplier_listing_id")) if payload.get("supplier_listing_id") else None
    except (TypeError,ValueError): raise HTTPException(422,"Choose a valid supplier.")
    supplier=db.get(SupplierListing,supplier_id) if supplier_id else None
    if supplier_id and (not supplier or not supplier.active): raise HTTPException(404,"Supplier listing is unavailable.")
    supplier_name=(supplier.supplier_name if supplier else str(payload.get("supplier_name","Direct customer/order"))).strip()[:180]
    item=str(payload.get("item_or_service","")).strip()[:240]
    if not item: raise HTTPException(422,"Describe the product or service you want to order.")
    try: qty=float(payload.get("quantity",1)); total=round(float(payload["quoted_total"])*100) if payload.get("quoted_total") not in (None,"") else None
    except (ValueError,TypeError): raise HTTPException(422,"Quantity and total must be valid numbers.")
    if qty<=0 or (total is not None and total<0): raise HTTPException(422,"Quantity must be positive and total cannot be negative.")
    row=BusinessOrder(user_id=user.id,supplier_listing_id=supplier_id,supplier_name=supplier_name,item_or_service=item,quantity=str(qty),quoted_total=total,delivery_address=str(payload.get("delivery_address",""))[:300],notes=str(payload.get("notes",""))[:3000],status="requested")
    db.add(row); db.commit(); db.refresh(row)
    return {"message":f"Order request #{row.id} saved. Contact the supplier to confirm price, availability, delivery and payment terms; no payment has been made.","order_id":row.id,"status":row.status}

@app.get("/api/orders")
def list_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows=db.scalars(select(BusinessOrder).where(BusinessOrder.user_id==user.id).order_by(desc(BusinessOrder.id)).limit(200)).all()
    return [{"id":r.id,"supplier_name":r.supplier_name,"item_or_service":r.item_or_service,"quantity":r.quantity,"quoted_total":r.quoted_total/100 if r.quoted_total is not None else None,"delivery_address":r.delivery_address,"notes":r.notes,"status":r.status,"created_at":str(r.created_at)} for r in rows]

@app.patch("/api/orders/{order_id}")
def update_order(order_id:int,payload:dict,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.scalar(select(BusinessOrder).where(BusinessOrder.id==order_id,BusinessOrder.user_id==user.id))
    if not row: raise HTTPException(404,"Order not found.")
    status=str(payload.get("status",row.status))
    if status not in {"requested","supplier_contacted","quoted","accepted","in_progress","delivered","cancelled"}: raise HTTPException(422,"Invalid order status.")
    row.status=status; db.commit()
    return {"message":f"Order #{order_id} status updated to {status.replace('_',' ')}.","status":status}

DOCUMENT_GUIDES = {
 "fnb_business_account": [("Identity document","Certified ID/passport for relevant owners or authorised signatories; check the bank's current rules."),("Business registration documents","CIPC registration and founding documents if operating as a registered company; requirements differ by entity type."),("Proof of business/residential address","Recent proof accepted by the bank."),("Tax details","SARS tax number or relevant tax information if requested."),("Authority to open account","Resolution or mandate for companies where applicable."),("Business profile","MALI MODE can draft a profile from your saved business details."),("Financial records","Recent bank statements, management accounts or financial statements if requested for the product selected.")],
 "tender": [("Tender/RFQ notice and returnables","Download the actual notice and follow its exact mandatory-document list."),("CSD registration report","Often requested for South African government suppliers; verify the specific notice."),("CIPC/company documents","If the tender requires a registered entity."),("SARS tax compliance status","Check the buyer's stated tax compliance requirement."),("B-BBEE affidavit/certificate","Only where required and appropriate to your entity and turnover."),("Proof of bank account","Use a bank-issued confirmation, not a screenshot of account credentials."),("Capability statement and relevant experience","Describe services, capacity, references and past work truthfully."),("Pricing schedule / quotation","Complete the buyer's own pricing forms and comply with the scope."),("Health and safety / industry licences","Only where applicable to the tender and industry.")],
 "funding": [("Business plan and use of funds","Explain what the money will pay for and expected outcomes."),("Founder identity and business profile","Use accurate owner and entity information."),("Financial statements or management accounts","Prepare from verified records; label internal reports as management accounts, not audited statements."),("Cash-flow forecast and budget","State assumptions and show how estimates were calculated."),("Bank statements","Provide only through the funder's official secure process."),("Quotes for equipment or project costs","Use current supplier quotations."),("Registration, tax and compliance documents","Depends on the funder and product."),("Proof of demand and track record","Orders, invoices, contracts, sales history and customer evidence where available.")],
 "financial_records": [("Income and expense ledger","Transaction-level record with dates, descriptions, categories and supporting references."),("Monthly profit and loss statement","Summarises income and expenses for a stated period; requires complete records."),("Cash-flow summary","Tracks money received and paid; not the same as profit."),("Accounts receivable / unpaid invoices","List customers, invoice dates, amounts due and due dates."),("Accounts payable / supplier balances","List unpaid supplier bills and due dates."),("Asset and liability register","Record business equipment, loans and other obligations if applicable."),("Stock report","Only for businesses that track inventory; use actual counts for reliable stock on hand."),("Supporting evidence","Invoices, receipts, bank statements and contracts; reconcile these before external submission.")]
}

def _document_checklist(kind, profile, tx_count):
    name=profile.get("business_name") or "Your business"; sector=(profile.get("business_type") or "business").lower()
    guide=DOCUMENT_GUIDES.get(kind,DOCUMENT_GUIDES["financial_records"])
    items=[]
    for title,why in guide:
        status="draftable" if title in {"Business profile","Capability statement and relevant experience","Business plan and use of funds","Income and expense ledger","Monthly profit and loss statement","Cash-flow summary","Accounts receivable / unpaid invoices","Accounts payable / supplier balances","Stock report"} else "external_or_user_supplied"
        items.append({"document":title,"why":why,"status":status,"available_to_generate":status=="draftable"})
    items.append({"document":"Profile details to verify","why":f"Confirm that {name}, business type ({sector}) and contact details are current before using any generated document.","status":"review_required","available_to_generate":False})
    items.append({"document":"Transaction-history readiness","why":f"MALI MODE currently has {tx_count} saved transaction records. Reports are only as complete as the records entered; reconcile against receipts and bank statements.","status":"review_required","available_to_generate":kind=="financial_records" and tx_count>0})
    return items

@app.get("/api/documents/checklist")
def documents_checklist(kind:str="tender",user:User=Depends(current_user),db:Session=Depends(get_db)):
    if kind not in DOCUMENT_GUIDES: raise HTTPException(422,"Choose fnb_business_account, tender, funding or financial_records.")
    _,profile=profile_data(db,user); tx_count=len(db.scalars(select(TransactionRecord).where(TransactionRecord.user_id==user.id)).all())
    titles={"fnb_business_account":"Business bank account preparation","tender":"Tender / RFQ application readiness","funding":"Funding application readiness","financial_records":"Business financial records"}
    return {"kind":kind,"title":titles[kind],"business_name":profile.get("business_name","Your business"),"notice":"This is a general preparation guide, not a guarantee of eligibility. Always follow the bank, funder or tender's current official notice. Requirements vary by entity type and opportunity.","items":_document_checklist(kind,profile,tx_count)}

@app.post("/api/documents/opportunity-review")
def review_opportunity(payload:dict,user:User=Depends(current_user),db:Session=Depends(get_db)):
    notice=str(payload.get("notice_text","")).strip()
    if len(notice)<30: raise HTTPException(422,"Paste the tender/RFQ or funding opportunity requirements (at least 30 characters).")
    if len(notice)>18000: raise HTTPException(413,"Opportunity text is too long. Paste the eligibility and required-documents sections only.")
    _,profile=profile_data(db,user)
    result={"ai_used":False,"summary":"","requirements":[],"missing_questions":[],"notice":"This analysis is a helper only. The original notice is authoritative; confirm requirements and deadlines with the issuing organisation."}
    key=os.getenv("OPENAI_API_KEY")
    if key:
        try:
            import urllib.request
            prompt=("Analyse the opportunity text for a South African youth-founded business. Return ONLY valid JSON with keys summary (string), requirements (array of objects with document, reason, status where status is required/conditional/unclear), missing_questions (array of strings). Do not invent requirements. Mark ambiguous items unclear and tell user to verify the original notice. Tailor fit discussion to this business profile: "+json.dumps({k:profile.get(k) for k in ["business_name","business_type","location","product_service","registration_status","experience"]},ensure_ascii=False)+". Opportunity text: "+notice)
            body=json.dumps({"model":os.getenv("OPENAI_MODEL","gpt-4o-mini"),"messages":[{"role":"system","content":"You help small businesses interpret procurement and funding notices. Never guarantee eligibility. Output valid JSON only."},{"role":"user","content":prompt}],"response_format":{"type":"json_object"},"temperature":0.1}).encode()
            req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=body,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(req,timeout=25) as response: data=json.loads(response.read().decode())
            result.update(json.loads(data["choices"][0]["message"]["content"])); result["ai_used"]=True
        except Exception as exc:
            logging.warning("Opportunity AI review failed: %s",exc); result["notice"] += " AI analysis was unavailable, so no AI-generated requirements are shown."
    if not result["ai_used"]:
        result["summary"]="AI review is not available. Use the checklist below as a general starting point and manually extract every mandatory requirement from the official notice."
        result["requirements"]=[{"document":"Original notice and returnables list","reason":"Read the issuing organisation's mandatory submission list directly.","status":"required"},{"document":"Business registration, tax and supplier records","reason":"Check whether each item is mandatory for this specific opportunity and entity type.","status":"unclear"},{"document":"Pricing, capability and supporting evidence","reason":"Use the forms and evidence requested by the notice; do not substitute generic documents where a prescribed form exists.","status":"unclear"}]
    return result

@app.post("/api/documents/generate")
def generate_founder_document(payload:dict,user:User=Depends(current_user),db:Session=Depends(get_db)):
    kind=str(payload.get("kind","business_profile")); _,p=profile_data(db,user)
    if kind not in {"business_profile","capability_statement","income_expense_summary","profit_loss","cash_flow","receivables_payables","funding_concept"}: raise HTTPException(422,"Choose a supported document type.")
    tx=db.scalars(select(TransactionRecord).where(TransactionRecord.user_id==user.id).order_by(TransactionRecord.transaction_date)).all()
    business=p.get("business_name","Your business"); sector=p.get("business_type","Not supplied"); service=p.get("product_service","Not supplied"); location=p.get("location","Not supplied")
    sales=sum(r.amount for r in tx if r.transaction_type=="Sale")/100; costs=sum(r.amount for r in tx if r.transaction_type in {"Purchase","Expense"})/100; balance=sales-costs
    if kind in {"income_expense_summary","profit_loss"}:
        title="Draft business income and expense summary" if kind=="income_expense_summary" else "Draft management profit and loss statement"
        content=f"{title}\nBusiness: {business}\nBusiness type: {sector}\nPeriod covered: {tx[0].transaction_date if tx else 'No records'} to {tx[-1].transaction_date if tx else 'No records'}\nSaved records analysed: {len(tx)}\nRecorded sales/income: R{sales:,.2f}\nRecorded purchases and expenses: R{costs:,.2f}\nRecorded difference before adjustments: R{balance:,.2f}\n\nIMPORTANT: This is an automatically prepared internal management summary from MALI MODE entries only. It is not audited, reviewed, tax-certified or a complete set of financial statements. Reconcile it against bank statements, invoices, receipts, tax records, inventory and liabilities. Refunds, VAT, depreciation, loans and unpaid invoices may require separate treatment."
    elif kind=="cash_flow":
        inflow=sum(r.amount for r in tx if r.transaction_type=="Sale")/100; outflow=sum(r.amount for r in tx if r.transaction_type in {"Purchase","Expense"})/100
        title="Draft recorded cash movement summary"; content=f"{title}\nBusiness: {business}\nRecords analysed: {len(tx)}\nRecorded sales/inflows proxy: R{inflow:,.2f}\nRecorded purchases/expenses proxy: R{outflow:,.2f}\nNet recorded difference: R{inflow-outflow:,.2f}\n\nThis is not a bank-reconciled cash flow statement. Transaction types alone do not prove cash was received or paid. Reconcile payment status and bank activity before external use."
    elif kind=="receivables_payables":
        title="Receivables and payables worksheet"; content=f"{title}\nBusiness: {business}\n\nAdd each unpaid customer invoice: customer, invoice number, issue date, due date, amount and payment status.\n\nAdd each unpaid supplier bill: supplier, invoice number, issue date, due date, amount and payment status.\n\nThis worksheet is a blank working template because MALI MODE's current ledger does not yet reliably connect transactions to invoices or payment allocations. Do not treat it as a populated balance report."
    elif kind=="funding_concept":
        title="Draft funding concept note"; content=f"FUNDING CONCEPT NOTE — DRAFT\nBusiness: {business}\nSector: {sector}\nLocation: {location}\nOffer: {service}\nFunding need stated in profile: R{float(p.get('funding_needed') or 0):,.2f}\n\nPurpose of funding: [Founder to complete]\nBudget breakdown: [Attach current quotations]\nExpected outcomes: [Add measurable outcomes]\nEvidence of demand: [Attach orders, invoices, contracts or customer evidence]\nFinancial evidence: {len(tx)} transaction records are saved in MALI MODE; reconcile and attach appropriate supporting records.\n\nThis is a draft template, not a funding approval or a claim that the business meets any funder's criteria."
    else:
        title="Business profile" if kind=="business_profile" else "Business capability statement"
        content=f"{title.upper()}\nBusiness name: {business}\nBusiness type: {sector}\nLocation: {location}\nProducts/services: {service}\nTarget customers: {p.get('target_customers','Not supplied')}\nBusiness experience: {p.get('experience','Not supplied')}\nContact: {user.full_name} · {user.email} · {user.phone}\n\n{('CAPABILITY STATEMENT' if kind=='capability_statement' else 'BUSINESS PROFILE')}\nWhat we do: {service}\nWhy customers choose us: [Add verified differentiators]\nCapacity and service area: [Complete with accurate details]\nRelevant experience / references: [Add only verifiable examples]\nRegistration / tax / CSD status: [Confirm and attach current evidence if applicable]\n\nReview all placeholders and verify every statement before sending to a buyer or funder."
    row=FounderDocument(user_id=user.id,document_type=kind,title=title,content=content); db.add(row); db.commit(); db.refresh(row)
    return {"message":"Draft generated from your saved profile and available transaction history. Review every figure and placeholder before external use.","id":row.id,"title":title,"content":content,"download_url":f"/api/documents/{row.id}/pdf"}

@app.get("/api/documents/{document_id}/pdf")
def download_founder_document(document_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.scalar(select(FounderDocument).where(FounderDocument.id==document_id,FounderDocument.user_id==user.id))
    if not row: raise HTTPException(404,"Document not found.")
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=45,leftMargin=45,topMargin=45,bottomMargin=45); styles=getSampleStyleSheet(); story=[Paragraph(row.title,styles["Title"]),Spacer(1,12)]
    for line in row.content.splitlines(): story.append(Paragraph(line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") or " ",styles["BodyText"])); story.append(Spacer(1,6))
    story.append(Spacer(1,10)); story.append(Paragraph("Generated by MALI MODE. Draft only — verify details and external requirements before use.",styles["Italic"])); doc.build(story); buf.seek(0)
    filename="".join(c for c in row.title.lower().replace(" ","-") if c.isalnum() or c=="-")[:70]+".pdf"
    return StreamingResponse(buf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{filename}"'})
