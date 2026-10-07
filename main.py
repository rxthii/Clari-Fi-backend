from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

app = FastAPI(title="Clari-Fi Agentic Finance Backend")

# Allow React Frontend to connect to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# MOCK DATABASE (Hackathon Sandboxed Data)
# ==========================================
MOCK_USER = {
    "name": "Rithika",
    "account_id": "ACC-99201",
    "balance": 1240.50,
    "budget_limit": 100.00,  # Weekend dining limit
    # Fixed daily commitments (e.g., $40 daily auto/commute allowance)
    "fixed_daily_expenses": [
        {"id": 1, "title": "Auto / Daily Commute", "daily_amount": 40.00, "active": True}
    ],
    "transactions": [
        {"id": 1, "merchant": "Starbucks", "amount": 12.50, "category": "Dining", "date": "2026-10-02"},
        {"id": 2, "merchant": "Amazon", "amount": 45.00, "category": "Shopping", "date": "2026-10-01"},
        {"id": 3, "merchant": "Netflix", "amount": 19.99, "category": "Subscriptions", "date": "2026-09-28", "flagged": True, "note": "Price increased by $4/mo!"},
        {"id": 4, "merchant": "Uber", "amount": 24.30, "category": "Transport", "date": "2026-09-27"},
    ]
}

# ==========================================
# REQUEST / RESPONSE MODELS
# ==========================================
class ChatRequest(BaseModel):
    user_id: str
    message: str

class QRScanRequest(BaseModel):
    qr_payload: str  # e.g., "upi://pay?pa=sahana@upi&pn=Sahana&am=50.00"

class PaymentConfirmRequest(BaseModel):
    draft_id: str
    amount: float
    recipient: str
    password: str

class FixedExpenseRequest(BaseModel):
    title: str
    daily_amount: float
    active: bool

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/")
def home():
    return {"status": "Clari-Fi Backend is Online!"}

# --- 1. PROACTIVE GUARDRAIL ENDPOINT ---
@app.get("/api/guardrails/alerts")
def get_proactive_alerts():
    """Scans accounts automatically for price spikes, budget caps, and daily fixed commitments."""
    alerts = []
    
    # Subscription Price Spike Detection
    for tx in MOCK_USER["transactions"]:
        if tx.get("flagged"):
            alerts.append({
                "type": "SUBSCRIPTION_SPIKE",
                "severity": "WARNING",
                "message": f"Alert: {tx['merchant']} increased charge to ${tx['amount']}/mo ({tx['note']})",
                "action_suggested": "Cancel Subscription or Request Refund"
            })
            
    # Category Spending Warning
    dining_spent = sum(t["amount"] for t in MOCK_USER["transactions"] if t["category"] == "Dining")
    if dining_spent > 80:
        alerts.append({
            "type": "BUDGET_CAP_WARNING",
            "severity": "INFO",
            "message": f"You've used ${dining_spent:.2f} of your $100 Dining budget this week.",
            "action_suggested": "Temporarily cap debit card limit?"
        })

    # Daily Fixed Expenses Projection Check
    active_daily_fixed = sum(item["daily_amount"] for item in MOCK_USER["fixed_daily_expenses"] if item["active"])
    days_left_in_month = 26  # Mock remaining days
    projected_fixed_cost = active_daily_fixed * days_left_in_month
    
    if MOCK_USER["balance"] < projected_fixed_cost:
        alerts.append({
            "type": "FIXED_EXPENSE_RUNWAY_WARNING",
            "severity": "WARNING",
            "message": f"Alert: Based on your set daily expense (${active_daily_fixed:.2f}/day for auto/commute), you need ${projected_fixed_cost:.2f} for the rest of the month. Current balance: ${MOCK_USER['balance']:.2f}.",
            "action_suggested": "Adjust daily auto expense allowance or pause non-essential purchases."
        })

    return {"alerts": alerts}

# --- 2. FIXED DAILY EXPENSES ENDPOINT ---
@app.post("/api/expenses/fixed")
def set_fixed_expense(payload: FixedExpenseRequest):
    """Allows user to set, update, or pause their daily baseline fixed costs (e.g., $40/day auto)."""
    MOCK_USER["fixed_daily_expenses"] = [{
        "id": 1,
        "title": payload.title,
        "daily_amount": payload.daily_amount,
        "active": payload.active
    }]
    return {
        "status": "UPDATED",
        "message": f"Set fixed daily spending for '{payload.title}' to ${payload.daily_amount:.2f}/day.",
        "fixed_expenses": MOCK_USER["fixed_daily_expenses"]
    }

# --- 3. QR CODE SCAN & PARSE ENDPOINT ---
@app.post("/api/qr/parse")
def parse_qr_code(payload: QRScanRequest):
    """Parses scanned QR payload and generates an actionable payment draft."""
    qr_str = payload.qr_payload.strip()

    recipient = "Merchant/User"
    amount = 0.0

    if "upi://" in qr_str or "pay?" in qr_str:
        parsed_url = urlparse(qr_str)
        query_params = parse_qs(parsed_url.query)
        
        recipient = query_params.get("pn", query_params.get("pa", ["Sahana"]))[0]
        amount_str = query_params.get("am", ["50.00"])[0]
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 50.00
    else:
        parts = qr_str.split(",")
        if len(parts) >= 2:
            recipient = parts[0].strip()
            amount = float(parts[1].strip())
        else:
            recipient = qr_str
            amount = 50.00

    return {
        "status": "QR_PARSED",
        "draft": {
            "draft_id": "QR_DRAFT_9910",
            "recipient": recipient,
            "amount": amount,
            "current_balance": MOCK_USER["balance"],
            "requires_password": True
        }
    }

# --- 4. CHAT ROUTER ENDPOINT ---
@app.post("/api/chat")
def handle_chat_query(payload: ChatRequest):
    user_text = payload.message.lower()

    if "balance" in user_text or "how much" in user_text:
        return {
            "agent": "AnalyticsAgent",
            "response_type": "TEXT",
            "message": f"Hi {MOCK_USER['name']}, your current account balance is **${MOCK_USER['balance']:,.2f}**."
        }
    elif "fixed" in user_text or "daily" in user_text or "auto" in user_text:
        fixed_items = MOCK_USER["fixed_daily_expenses"]
        summary = ", ".join([f"{item['title']}: ${item['daily_amount']:.2f}/day" for item in fixed_items if item["active"]])
        return {
            "agent": "GuardrailAgent",
            "response_type": "TEXT",
            "message": f"Your active daily fixed expenses: {summary}. Clari-Fi automatically accounts for this baseline in your budget."
        }
    elif "alert" in user_text or "subscription" in user_text or "flag" in user_text:
        alerts = get_proactive_alerts()["alerts"]
        return {
            "agent": "GuardrailAgent",
            "response_type": "ALERTS",
            "message": "Here are the proactive alerts caught by Clari-Fi guardrails:",
            "data": alerts
        }
    elif "send" in user_text or "transfer" in user_text or "pay" in user_text:
        return {
            "agent": "ExecutionAgent",
            "response_type": "PAYMENT_DRAFT",
            "message": "I have created a pending payment draft. Please confirm with your transaction PIN to dispatch funds.",
            "draft": {
                "draft_id": "DRAFT_88321",
                "recipient": "Sahana",
                "amount": 50.00,
                "status": "PENDING_USER_PASSWORD"
            }
        }

    return {
        "agent": "GeneralAgent",
        "response_type": "TEXT",
        "message": f"I parsed your prompt: '{payload.message}'."
    }

# --- 5. HUMAN-IN-THE-LOOP PAYMENT EXECUTION ---
@app.post("/api/transfer/confirm")
def confirm_payment_draft(payload: PaymentConfirmRequest):
    if payload.password != "1234":
        raise HTTPException(status_code=401, detail="Incorrect 4-digit PIN. Transfer blocked.")

    if MOCK_USER["balance"] < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds.")

    # Deduct amount
    MOCK_USER["balance"] -= payload.amount
    
    # Add to transaction history
    MOCK_USER["transactions"].insert(0, {
        "id": len(MOCK_USER["transactions"]) + 1,
        "merchant": f"Payment to {payload.recipient}",
        "amount": payload.amount,
        "category": "Transfer",
        "date": "2026-10-04"
    })

    return {
        "status": "SUCCESS",
        "message": f"Successfully transferred ${payload.amount:.2f} to {payload.recipient}!",
        "new_balance": MOCK_USER["balance"]
    }


 

   