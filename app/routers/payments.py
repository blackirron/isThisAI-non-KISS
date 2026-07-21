import razorpay
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.dependencies import get_current_user
from app.models import Payment, User
from app.routers.auth import _user_out
from app.schemas import CreateOrderResponse, UserOut, VerifyPaymentRequest

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _client() -> razorpay.Client:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments aren't configured yet — RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET missing.",
        )
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Opens a Razorpay order for a one-time "lifetime Pro" purchase. No
    money moves here — this just reserves an order id that the frontend
    hands to Razorpay's Checkout widget. The account is only upgraded once
    /verify confirms a signed payment against this exact order."""
    if current_user.plan == "pro":
        raise HTTPException(status_code=400, detail="This account is already Pro.")

    amount_paise = settings.PRO_PRICE_INR * 100
    client = _client()

    try:
        order = client.order.create(
            {
                "amount": amount_paise,
                "currency": "INR",
                "notes": {"user_id": current_user.id, "email": current_user.email},
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not start payment: {exc}")

    payment = Payment(
        user_id=current_user.id,
        razorpay_order_id=order["id"],
        amount_paise=amount_paise,
        currency="INR",
        status="created",
    )
    db.add(payment)
    db.commit()

    return CreateOrderResponse(
        order_id=order["id"],
        amount=amount_paise,
        currency="INR",
        key_id=settings.RAZORPAY_KEY_ID,
        name="IsThisAI Pro",
        description="Lifetime Pro access — unlimited examinations",
    )


@router.post("/verify", response_model=UserOut)
def verify_payment(
    payload: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verifies Razorpay's HMAC signature server-side — the only step that
    actually proves the payment happened — then flips the account to Pro.
    Never trust a client-side 'payment succeeded' callback on its own."""
    payment = (
        db.query(Payment)
        .filter(Payment.razorpay_order_id == payload.razorpay_order_id)
        .first()
    )
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Order not found for this account.")

    if payment.status == "paid":
        # Already processed (e.g. duplicate callback) — just return current state.
        return _user_out(current_user)

    client = _client()
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
            }
        )
    except razorpay.errors.SignatureVerificationError:
        payment.status = "failed"
        db.add(payment)
        db.commit()
        raise HTTPException(status_code=400, detail="Payment signature could not be verified.")

    payment.status = "paid"
    payment.razorpay_payment_id = payload.razorpay_payment_id
    payment.razorpay_signature = payload.razorpay_signature
    db.add(payment)

    current_user.plan = "pro"
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return _user_out(current_user)
