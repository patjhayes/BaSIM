import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from square import Square
from .auth_utils import get_current_user, get_current_admin, supabase_admin
from pydantic import BaseModel

router = APIRouter()

# Initialize Square Client
SQUARE_ACCESS_TOKEN = os.environ.get("SQUARE_ACCESS_TOKEN", "placeholder")
SQUARE_ENVIRONMENT = os.environ.get("SQUARE_ENVIRONMENT", "sandbox") # or 'production'
SQUARE_LOCATION_ID = os.environ.get("SQUARE_LOCATION_ID", "placeholder")
SQUARE_WEBHOOK_SIGNATURE_KEY = os.environ.get("SQUARE_WEBHOOK_SIGNATURE_KEY", "")

square_client = Square(
    access_token=SQUARE_ACCESS_TOKEN,
    environment=SQUARE_ENVIRONMENT,
)

class CreditAdjustment(BaseModel):
    project_code: str
    amount: int
    description: str

@router.get("/balance/{project_code}")
def get_balance(project_code: str, user: dict = Depends(get_current_user)):
    """Fetch the credit balance for a project (user must belong to same company)."""
    # 1. Verify project belongs to user's company
    proj_resp = supabase_admin.table('projects').select('*').eq('project_code', project_code).execute()
    if not proj_resp.data:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = proj_resp.data[0]
    if project['company_id'] != user['company_id'] and not user.get('is_admin'):
        raise HTTPException(status_code=403, detail="Not authorized to view this project")
        
    return {"project_code": project_code, "credit_balance": project['credit_balance']}

@router.post("/checkout/{project_code}")
def create_checkout_link(project_code: str, user: dict = Depends(get_current_user)):
    """Generates a Square checkout link to purchase 1000 credits for $100."""
    # Verify authorization
    proj_resp = supabase_admin.table('projects').select('*').eq('project_code', project_code).execute()
    if not proj_resp.data:
        # Create project entry if it doesn't exist
        supabase_admin.table('projects').insert({
            'project_code': project_code,
            'company_id': user['company_id'],
            'credit_balance': 0
        }).execute()
    elif proj_resp.data[0]['company_id'] != user['company_id'] and not user.get('is_admin'):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Generate unique idempotency key
    idempotency_key = str(uuid.uuid4())
    
    body = {
        "idempotency_key": idempotency_key,
        "order": {
            "location_id": SQUARE_LOCATION_ID,
            "line_items": [
                {
                    "name": "1,000 BaSIM Simulation Credits",
                    "quantity": "1",
                    "base_price_money": {
                        "amount": 10000, # $100.00 in cents
                        "currency": "AUD"
                    }
                }
            ],
            # Pass the project_code in metadata so webhook knows where to apply credits
            "metadata": {
                "project_code": project_code,
                "user_id": user['id']
            }
        },
        "checkout_options": {
            # Provide your domain here, or standard redirect
            "redirect_url": "https://basim.innealta.com.au/billing"
        }
    }
    
    result = square_client.checkout.create_payment_link(body)
    
    if result.is_success():
        return {"payment_url": result.body['payment_link']['url']}
    elif result.is_error():
        raise HTTPException(status_code=500, detail=result.errors)

@router.post("/webhook/square")
async def square_webhook(request: Request):
    """Handle Square webhooks (specifically payment.updated / payment.created)."""
    # Note: In production, you must verify the signature using SQUARE_WEBHOOK_SIGNATURE_KEY
    # from the `x-square-hmacsha256-signature` header.
    
    body = await request.json()
    
    # We only care about successful payments
    if body.get('type') == 'payment.updated' or body.get('type') == 'payment.created':
        payment = body['data']['object']['payment']
        status = payment.get('status')
        
        if status == 'COMPLETED':
            # Need to get the order to read metadata
            order_id = payment.get('order_id')
            if order_id:
                order_res = square_client.orders.retrieve_order(order_id)
                if order_res.is_success():
                    order = order_res.body['order']
                    metadata = order.get('metadata', {})
                    project_code = metadata.get('project_code')
                    
                    if project_code:
                        # Add 1000 credits
                        _add_credits(project_code, 1000, 'purchase', description=f"Square Payment {payment['id']}")
                        
    return {"status": "ok"}

@router.post("/admin/adjust_credits")
def admin_adjust_credits(adjustment: CreditAdjustment, admin: dict = Depends(get_current_admin)):
    """Admin endpoint to manually add or deduct credits."""
    _add_credits(adjustment.project_code, adjustment.amount, 'manual_adjustment', admin['id'], adjustment.description)
    return {"status": "success", "adjusted": adjustment.amount}

def _add_credits(project_code: str, amount: int, type_str: str, user_id: str = None, description: str = None):
    # Atomic update via RPC or read-update-write
    # Using read-update-write here for simplicity, but RPC is safer for concurrency.
    proj_resp = supabase_admin.table('projects').select('*').eq('project_code', project_code).execute()
    if not proj_resp.data:
        return
        
    current_balance = proj_resp.data[0]['credit_balance']
    new_balance = current_balance + amount
    
    # 1. Update balance
    supabase_admin.table('projects').update({'credit_balance': new_balance}).eq('project_code', project_code).execute()
    
    # 2. Record transaction
    tx = {
        'project_code': project_code,
        'amount': amount,
        'type': type_str,
        'description': description
    }
    if user_id:
        tx['user_id'] = user_id
        
    supabase_admin.table('transactions').insert(tx).execute()
