"""Payment integration boundary for FOODíE.

The included gateway is a local demonstration only. It does not connect to GCash,
Maya, QR Ph, a bank, or any payment processor. A production adapter must create
payment sessions server-side and verify signed provider callbacks before an order
can be marked as paid.
"""

from abc import ABC, abstractmethod
import secrets


class PaymentGateway(ABC):
    """Interface implemented by a future approved payment provider adapter."""

    @abstractmethod
    def create_payment_session(self, order_number, amount, currency="PHP"):
        raise NotImplementedError

    @abstractmethod
    def verify_payment(self, provider_payload, signature):
        raise NotImplementedError


class DemoPaymentGateway(PaymentGateway):
    """Local-only simulator. No payment request or money transfer occurs."""

    def create_payment_session(self, order_number, amount, currency="PHP"):
        return {
            "mode": "DEMO",
            "order_number": order_number,
            "amount": round(float(amount), 2),
            "currency": currency,
            "reference": f"DEMO-{secrets.token_hex(5).upper()}",
            "message": "Simulation only. No real payment was initiated.",
        }

    def verify_payment(self, provider_payload, signature):
        # Demo mode must never claim to verify a real provider payment.
        return False
