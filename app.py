from fastapi import FastAPI, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, Table, MetaData
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from PIL import Image
import pytesseract
import io
import csv
import os
# Pydantic models for authentication

from pydantic import BaseModel

class UserCreate(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

# --- Authentication Helper Functions ---
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

# Password hashing setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a plain password."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

# JWT setup
JWT_SECRET = "a_very_secure_random_secret"   # Replace with a secure random string
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

def create_access_token(data: dict, expires_delta: int = JWT_EXPIRE_MINUTES) -> str:
    """Create a JWT token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token
# ----------------- AUTH ROUTES -----------------
from fastapi import HTTPException, status

@app.post("/auth/register", response_model=Token)
def register(user: UserCreate):
    db = SessionLocal()
    existing = db.execute(users.select().where(users.c.email == user.email)).first()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    ph = hash_password(user.password)
    db.execute(users.insert().values(email=user.email, password_hash=ph))
    db.commit()
    user_row = db.execute(users.select().where(users.c.email == user.email)).first()
    db.close()
    token = create_access_token({"sub": user_row.id})
    return {"access_token": token, "token_type": "bearer"}
# ------------------- AUTH MIDDLEWARE -------------------
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    from jose import jwt
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    user_id = payload.get("sub")
    
    db = SessionLocal()
    user = db.execute(users.select().where(users.c.id == user_id)).first()
    db.close()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
@app.post("/auth/login", response_model=Token)
def login(user: UserCreate):
    db = SessionLocal()
    row = db.execute(users.select().where(users.c.email == user.email)).first()
    db.close()
    if not row or not verify_password(user.password, row.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": row.id})
    return {"access_token": token, "token_type": "bearer"}
# AI simulation function (replace with OpenAI call)
def categorize_expense(text):
    text = text.lower()
    if "food" in text or "restaurant" in text:
        return "Food"
    elif "taxi" in text or "uber" in text:
        return "Travel"
    else:
        return "Other"

import re

def extract_amount(text):
    text_lower = text.lower()

    patterns = [
        r"total[:\s]*\$?([\d.,]+)",
        r"amount[:\s]*\$?([\d.,]+)",
        r"balance[:\s]*\$?([\d.,]+)",
        r"grand total[:\s]*\$?([\d.,]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except:
                pass

    numbers = []
    for word in text.replace("\n"," ").split(" "):
        word_clean = word.replace("$","").replace(",","")
        try:
            numbers.append(float(word_clean))
        except:
            continue

    return max(numbers) if numbers else 0.0


def extract_date(text):
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}/\d{2}/\d{4})",
        r"(\d{2}-\d{2}-\d{4})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except:
                try:
                    return datetime.strptime(match.group(1), "%m/%d/%Y").date()
                except:
                    try:
                        return datetime.strptime(match.group(1), "%m-%d-%Y").date()
                    except:
                        continue

    return datetime.today().date()

# Setup FastAPI
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Setup SQLite DB
DB_PATH = "data/receipts.db"
os.makedirs("data", exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}")
metadata = MetaData()
# Setup SQLite DB
DB_PATH = "data/receipts.db"
os.makedirs("data", exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}")
metadata = MetaData()

# Users table
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String, unique=True, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("is_paid", Integer, default=0),            # 0 = free, 1 = paid
    Column("subscription_expires", Date, nullable=True)
)

# Receipts table with user_id and optional image_url
receipts = Table(
    "receipts", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=True),
    Column("vendor", String),
    Column("amount", Float),
    Column("category", String),
    Column("date", Date),
    Column("raw_text", String),
    Column("image_url", String, nullable=True)
)

metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)
# Dependency to get a DB session
from sqlalchemy.orm import Session

def get_db():
    db = SessionLocal()  # create a session
    try:
        yield db          # provide it to the route
    finally:
        db.close()        # always close after the route finishes

# Home page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Upload receipt
@app.post("/upload")
async def upload_receipt(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)  # <-- add this
):
    contents = await file.read()
    image = Image.open(io.BytesIO(contents))

    text = pytesseract.image_to_string(image)

    vendor = "Unknown Vendor"
    for line in text.split("\n"):
        if line.strip():
            vendor = line.strip()[:30]
            break

    amount = extract_amount(text)
    date_found = extract_date(text)
    category = categorize_expense(text)

    db = SessionLocal()
    db.execute(
        receipts.insert().values(
            user_id=current_user.id,  # <-- attach the logged-in user
            vendor=vendor,
            amount=amount,
            category=category,
            date=date_found,
            raw_text=text,
            image_url=None
        )
    )
    db.commit()
    db.close()

    return {
        "vendor": vendor,
        "amount": amount,
        "category": category,
        "date": str(date_found),
        "raw_text": text
    }

# Dashboard
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    current_user = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    rows = db.execute(receipts.select().where(receipts.c.user_id==current_user.id)).fetchall()
    return templates.TemplateResponse("dashboard.html", {"request": request, "entries": rows})

# Bank CSV import
@app.post("/import_csv")
async def import_csv(file: UploadFile = File(...)):
    contents = await file.read()
    reader = csv.DictReader(io.StringIO(contents.decode()))
    db = SessionLocal()
    for row in reader:
        amount = float(row.get("Amount", 0))
        vendor = row.get("Description", "Unknown")[:30]
        category = categorize_expense(vendor)
        db.add_all([receipts.insert().values(
            vendor=vendor,
            amount=amount,
            category=category,
            date=datetime.strptime(row.get("Date"), "%Y-%m-%d"),
            raw_text=""
        )])
    db.commit()
    db.close()
    return {"status": "Bank CSV imported successfully"}

# Export for tax
@app.get("/export")
async def export_csv():
    db = SessionLocal()
    result = db.execute(receipts.select()).fetchall()
    db.close()
    path = "data/export.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vendor", "Amount", "Category", "Date"])
        for r in result:
            writer.writerow([r.vendor, r.amount, r.category, r.date])
    return FileResponse(path, filename="export.csv")
