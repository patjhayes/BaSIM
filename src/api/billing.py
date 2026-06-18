import os
import uuid
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from .auth_utils import get_current_user, get_current_admin, supabase_admin
from pydantic import BaseModel

router = APIRouter()

# Initialize Stripe
stripe.api_key = os.environ.get("STRIPE_API_KEY", "placeholder")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

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
def create_checkout_link(project_code: str, request: Request, user: dict = Depends(get_current_user)):
    """Generates a Stripe checkout link to purchase 1000 credits for $100."""
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

    try:
        # Get the origin from the request to redirect back to the correct frontend URL
        origin = request.headers.get("origin", "https://basim-frontend.onrender.com")
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'aud',
                    'product_data': {
                        'name': '1,000 BaSIM Simulation Credits',
                    },
                    'unit_amount': 10000, # $100.00 in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{origin}/billing',
            cancel_url=f'{origin}/billing',
            client_reference_id=project_code,
            metadata={
                'project_code': project_code,
                'user_id': user['id']
            }
        )
        return {"payment_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks (specifically checkout.session.completed)."""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        # In production, verify the webhook signature
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            # Fallback for local testing without signature validation
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        project_code = session.get('metadata', {}).get('project_code')
        
        if project_code:
            # Add 1000 credits
            _add_credits(project_code, 1000, 'purchase', description=f"Stripe Checkout {session['id']}")
            
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
