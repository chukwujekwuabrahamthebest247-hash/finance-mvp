from fastapi import FastAPI, Request, UploadFile, File, Form
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
receipts = Table(
    "receipts", metadata,
    Column("id", Integer, primary_key=True),
    Column("vendor", String),
    Column("amount", Float),
    Column("category", String),
    Column("date", Date),
    Column("raw_text", String)
)
metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# Home page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Upload receipt
@app.post("/upload")
async def upload_receipt(file: UploadFile = File(...)):
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
            vendor=vendor,
            amount=amount,
            category=category,
            date=date_found,
            raw_text=text
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
async def dashboard(request: Request):
    db = SessionLocal()
    result = db.execute(receipts.select()).fetchall()
    db.close()
    
    total_expense = sum(r.amount for r in result)
    by_category = {}
    for r in result:
        by_category[r.category] = by_category.get(r.category, 0) + r.amount
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_expense": total_expense,
        "by_category": by_category,
        "entries": result
    })

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
