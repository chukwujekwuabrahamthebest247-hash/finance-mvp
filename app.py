#Force fresh build on Railway

#app.py — copy this entire file and replace your current app.py

from fastapi import FastAPI, Request, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, Table, MetaData
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
import io
import csv
import os
import re

#---------- Config ----------

DB_PATH = "data/receipts.db"
os.makedirs("data", exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
metadata = MetaData()

#---------- Tables ----------

users = Table(
"users", metadata,
Column("id", Integer, primary_key=True),
Column("email", String, unique=True, nullable=False),
Column("password_hash", String, nullable=False),
Column("is_paid", Integer, default=0),
Column("subscription_expires", Date, nullable=True)
)

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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

#---------- FastAPI app, templates, static ----------

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

#---------- Auth helpers ----------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = "change_this_to_a_random_secret"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

def hash_password(password: str) -> str:
return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_minutes: int = JWT_EXPIRE_MINUTES) -> str:
to_encode = data.copy()
expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
to_encode.update({"exp": expire})
return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

#---------- Pydantic models ----------

class UserCreate(BaseModel):
email: str
password: str

class Token(BaseModel):
access_token: str
token_type: str = "bearer"

#---------- DB dependency ----------

def get_db():
db = SessionLocal()
try:
yield db
finally:
db.close()

#---------- Utility: get_current_user ----------

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
try:
payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
except JWTError:
raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
user_id = payload.get("sub")
if user_id is None:
raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
row = db.execute(users.select().where(users.c.id == user_id)).first()
if not row:
raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
return row

#---------- Simple categorization + extractors ----------

def categorize_expense(text: str) -> str:
text = (text or "").lower()
if "food" in text or "restaurant" in text:
return "Food"
if "taxi" in text or "uber" in text:
return "Travel"
return "Other"

def extract_amount(text: str) -> float:
text_lower = (text or "").lower()
patterns = [r"total[:\s]$?([\d.,]+)", r"amount[:\s]$?([\d.,]+)", r"grand total[:\s]*$?([\d.,]+)"]
for p in patterns:
m = re.search(p, text_lower)
if m:
try:
return float(m.group(1).replace(",", ""))
except:
pass
numbers = []
for token in re.findall(r"[\d,]+(?:.\d+)?", text):
try:
numbers.append(float(token.replace(",", "")))
except:
pass
return max(numbers) if numbers else 0.0

def extract_date(text: str):
patterns = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}-\d{2}-\d{4})"]
for p in patterns:
m = re.search(p, text)
if m:
for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
try:
return datetime.strptime(m.group(1), fmt).date()
except:
pass
return datetime.today().date()

#---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
return templates.TemplateResponse("index.html", {"request": request})

@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(get_db)):
existing = db.execute(users.select().where(users.c.email == user.email)).first()
if existing:
raise HTTPException(status_code=400, detail="Email already registered")
ph = hash_password(user.password)
db.execute(users.insert().values(email=user.email, password_hash=ph))
db.commit()
user_row = db.execute(users.select().where(users.c.email == user.email)).first()
token = create_access_token({"sub": user_row.id})
return {"access_token": token, "token_type": "bearer"}

@app.post("/auth/login", response_model=Token)
def login(user: UserCreate, db: Session = Depends(get_db)):
row = db.execute(users.select().where(users.c.email == user.email)).first()
if not row or not verify_password(user.password, row.password_hash):
raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
token = create_access_token({"sub": row.id})
return {"access_token": token, "token_type": "bearer"}

@app.post("/upload")
async def upload_receipt(file: UploadFile = File(...), current_user = Depends(get_current_user), db: Session = Depends(get_db)):
contents = await file.read()
image = Image.open(io.BytesIO(contents))
text = pytesseract.image_to_string(image)

vendor = "Unknown Vendor"  
for line in text.splitlines():  
    if line.strip():  
        vendor = line.strip()[:100]  
        break  

amount = extract_amount(text)  
date_found = extract_date(text)  
category = categorize_expense(text)  

db.execute(receipts.insert().values(  
    user_id=current_user.id,  
    vendor=vendor,  
    amount=amount,  
    category=category,  
    date=date_found,  
    raw_text=text,  
    image_url=None  
))  
db.commit()  

return {"vendor": vendor, "amount": amount, "category": category, "date": str(date_found)}

@app.post("/import_csv")
async def import_csv(file: UploadFile = File(...), current_user = Depends(get_current_user), db: Session = Depends(get_db)):
contents = await file.read()
reader = csv.DictReader(io.StringIO(contents.decode()))
for row in reader:
try:
amount = float(row.get("Amount", 0))
except:
amount = 0.0
vendor = row.get("Description", "Unknown")[:100]
category = categorize_expense(vendor)
date_obj = None
try:
date_obj = datetime.strptime(row.get("Date"), "%Y-%m-%d").date()
except:
date_obj = datetime.today().date()
db.execute(receipts.insert().values(
user_id=current_user.id,
vendor=vendor,
amount=amount,
category=category,
date=date_obj,
raw_text=""
))
db.commit()
return {"status": "Bank CSV imported successfully"}

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
rows = db.execute(receipts.select().where(receipts.c.user_id == current_user.id)).fetchall()
return templates.TemplateResponse("dashboard.html", {"request": request, "entries": rows})

@app.get("/export")
def export_csv(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
rows = db.execute(receipts.select().where(receipts.c.user_id == current_user.id)).fetchall()
path = "data/export.csv"
with open(path, "w", newline="") as f:
writer = csv.writer(f)
writer.writerow(["Vendor", "Amount", "Category", "Date"])
for r in rows:
writer.writerow([r.vendor, r.amount, r.category, r.date])
return FileResponse(path, filename="export.csv")
