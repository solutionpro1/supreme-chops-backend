import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

app = FastAPI(title="Supreme Chops Core Enterprise API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "ts_live_your_actual_paystack_secret_key")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# --- SMTP MAIL SETTINGS FOR ALERTS ---
# These pull dynamically from your Render Environment Dashboard variables
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "junioradekeye@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "vpzqulajoqbewzwy")
ALERT_TEST_EMAIL = "junioradekeye@gmail.com"

USERS_FILE = "users_db.json"
ORDERS_FILE = "orders_log.json"

# --- EXTENDED SCHEMAS ---
class GooglePhoneRegister(BaseModel):
    name: str
    email: EmailStr
    phoneNumber: str
    googleIdToken: str

class UserLoginRequest(BaseModel):
    email: EmailStr
    googleIdToken: str

class CartItem(BaseModel):
    uniqueId: str
    name: str
    price: float
    quantity: int

class OrderRequest(BaseModel):
    email: EmailStr
    items: List[CartItem]

class StatusUpdateRequest(BaseModel):
    reference: str
    new_status: str

# --- FILE LOG ENGINE ---
def load_json_file(file_path: str) -> list:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_json_file(file_path: str, data: list):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- SILENT BACKGROUND EMAIL DISPATCHER ---
def send_checkout_alert_email(customer_email: str, phone: str, total_amount: float, items: list, reference: str):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = ALERT_TEST_EMAIL
        msg['Subject'] = f"⚠️ INTENT ALERT: Checkout Initialized ({reference})"
        
        items_text = ""
        for idx, it in enumerate(items):
            items_text += f"<li>{it['name']} (x{it['qty']}) - ₦{int(it['price'] * it['qty']):,}</li>"

        html_body = f"""
        <html>
            <body style="font-family: sans-serif; color: #333; line-height: 1.6;">
                <h2 style="color: #ea580c;">Supreme Chops Checkout Started</h2>
                <p>A user has initiated checkout and is currently viewing the Paystack portal:</p>
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr><td style="padding: 5px; font-weight: bold;">Customer Email:</td><td>{customer_email}</td></tr>
                    <tr><td style="padding: 5px; font-weight: bold;">User Phone:</td><td>{phone}</td></tr>
                    <tr><td style="padding: 5px; font-weight: bold;">Order Reference:</td><td><code>{reference}</code></td></tr>
                    <tr><td style="padding: 5px; font-weight: bold;">Total Intended Value:</td><td style="color: #ea580c; font-weight: bold;">₦{int(total_amount):,}</td></tr>
                </table>
                <h4 style="margin-bottom: 5px;">Items in Basket Selection:</h4>
                <ul>{items_text}</ul>
                <p style="font-size: 11px; color: #666; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
                    Follow up with this client via WhatsApp at <strong>{phone}</strong> if the order pipeline status does not update to 'Paid' shortly.
                </p>
            </body>
        </html>
        """
        msg.attach(MIMEText(html_body, 'html'))
        
        # 🔒 SWITCHED TO PORT 465 WITH SECURE SSL WRAPPER TO ACCESSIBLY BYPASS RENDER NETWORK BLOCKADES
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, ALERT_TEST_EMAIL, msg.as_string())
        server.quit()
        print(f"[SUCCESS] Silent intent email alert successfully transmitted to {ALERT_TEST_EMAIL}")
    except Exception as mail_err:
        print(f"[MAIL ERROR ENCOUNTERED] {str(mail_err)}")

# --- SOCIAL AUTH ENDPOINTS ---
@app.post("/api/auth/google-register")
async def google_register(user: GooglePhoneRegister):
    users = load_json_file(USERS_FILE)
    if any(u["email"] == user.email for u in users):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    
    new_user = {
        "name": user.name,
        "email": user.email,
        "phone": user.phoneNumber,
        "googleId": user.googleIdToken[:15]
    }
    users.append(new_user)
    save_json_file(USERS_FILE, users)
    return {"success": True, "message": "Secure social account generated!"}

@app.post("/api/auth/google-login")
async def google_login(payload: UserLoginRequest):
    users = load_json_file(USERS_FILE)
    matched = next((u for u in users if u["email"] == payload.email), None)
    if not matched:
        raise HTTPException(status_code=404, detail="No profile found. Please register your phone number first.")
    return {"success": True, "token": f"mock-jwt-{matched['email']}", "user": matched}

# --- CUSTOMER TRACKING HISTORY ---
@app.get("/api/customer/orders")
async def get_customer_orders(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header.")
    
    customer_email = authorization.replace("Bearer mock-jwt-", "").strip()
    all_orders = load_json_file(ORDERS_FILE)
    return {"success": True, "orders": [o for o in all_orders if o.get("customer_email") == customer_email][::-1]}

# --- ADMIN DECK CONTROL & STATUS TOGGLE ---
@app.get("/api/admin/orders")
async def admin_get_all_orders():
    all_orders = load_json_file(ORDERS_FILE)
    return {"success": True, "orders": all_orders[::-1]}

@app.post("/api/admin/update-status")
async def admin_update_order_status(payload: StatusUpdateRequest):
    allowed_milestones = ["Payment Received", "Processing", "Order on Delivery", "Order Delivered"]
    if payload.new_status not in allowed_milestones:
        raise HTTPException(status_code=400, detail="Invalid status milestone choice.")
        
    all_orders = load_json_file(ORDERS_FILE)
    found = False
    for order in all_orders:
        if order.get("reference") == payload.reference:
            order["order_status"] = payload.new_status
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Order reference matching tracking index not found.")
        
    save_json_file(ORDERS_FILE, all_orders)
    return {"success": True, "message": f"Order milestone shifted to '{payload.new_status}' successfully."}

# --- CHECKOUT INITIALIZATION ---
@app.post("/api/checkout/initialize-payment")
async def initialize_payment(order: OrderRequest, background_tasks: BackgroundTasks):
    if not order.items:
        raise HTTPException(status_code=400, detail="Your checkout cart is empty.")
    
    users = load_json_file(USERS_FILE)
    user_match = next((u for u in users if u["email"] == order.email), None)
    
    # Secure phone extraction parameter mapping
    user_phone = user_match.get("phone", "No Phone Linked") if user_match else "Unknown Phone"

    total_amount = sum(item.price * item.quantity for item in order.items)
    amount_in_kobo = int(total_amount * 100)
    
    paystack_url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "email": order.email,
        "amount": amount_in_kobo,
        "callback_url": FRONTEND_URL,
    }
    
    try:
        response = requests.post(paystack_url, json=payload, headers=headers)
        res_data = response.json()
        
        if response.status_code == 200 and res_data.get("status"):
            reference_code = res_data["data"]["reference"]
            formatted_items = [{"name": i.name, "qty": i.quantity, "price": i.price} for i in order.items]
            
            all_orders = load_json_file(ORDERS_FILE)
            all_orders.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reference": reference_code,
                "customer_email": order.email,
                "total_bill_with_vat": total_amount,
                "order_status": "Payment Received",
                "items": formatted_items
            })
            save_json_file(ORDERS_FILE, all_orders)
            
            # Fire email task asynchronously in the background worker frame
            background_tasks.add_task(
                send_checkout_alert_email,
                customer_email=order.email,
                phone=user_phone,
                total_amount=total_amount,
                items=formatted_items,
                reference=reference_code
            )
            
            return {"success": True, "checkout_url": res_data["data"]["authorization_url"]}
        else:
            raise HTTPException(status_code=400, detail=res_data.get("message", "Paystack failed."))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))