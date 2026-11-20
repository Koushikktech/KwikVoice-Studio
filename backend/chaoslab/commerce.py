from decimal import Decimal
from typing import Annotated

from pydantic import Field, ValidationError

from .consent import agreed
from .merchant import InputModel


class CartArgs(InputModel):
    cart_id: str


class CodArgs(CartArgs):
    amount: Annotated[Decimal, Field(ge=0, max_digits=11, decimal_places=2)]


class ConfirmOrderArgs(CodArgs):
    verified_address_landmark: str | None = Field(default=None, min_length=1, max_length=120)


class CallbackArgs(CartArgs):
    delay_minutes: int | None = Field(default=None, strict=True, ge=1, le=10080)
    reason: str | None = Field(default=None, min_length=1, max_length=160)


class CheckoutArgs(CodArgs):
    discount_percent: Annotated[int, Field(ge=0, le=30, strict=True)]


TOOLS = {
    "send_checkout_link": CheckoutArgs,
    "confirm_cod_order": ConfirmOrderArgs,
    "schedule_callback": CallbackArgs,
}

def tool_declarations() -> list[dict]:
    return [
        {
            "name": name,
            "description": description,
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "cart_id": {"type": "STRING"},
                    **({"amount": {"type": "NUMBER"}} if "amount" in model.model_fields else {}),
                    **({"verified_address_landmark": {"type": "STRING", "description": "A landmark confirmed by the shopper this turn. Omit if unknown."}}
                       if name == "confirm_cod_order" else {}),
                    **({"delay_minutes": {"type": "INTEGER", "description": "Requested delay in minutes, when specified."},
                        "reason": {"type": "STRING", "description": "Short reason for the callback."}}
                       if name == "schedule_callback" else {}),
                    **({"discount_percent": {"type": "INTEGER"}} if "discount_percent" in model.model_fields else {}),
                },
                "required": [field for field, info in model.model_fields.items() if info.is_required()],
            },
        }
        for (name, model), description in zip(TOOLS.items(), [
            "Create a mock UPI checkout after the caller agrees. Use the current cart ID, exact server UPI total and approved percentage.",
            "Confirm a mock COD order after the caller agrees. Use the current cart ID and exact server COD total.",
            "Schedule a mock callback after the caller agrees. Use the current cart ID.",
        ], strict=True)
    ]


def mock_tool(name: str, arguments: object, context: dict, latest_shopper_turn: str, offer: str | None = None) -> dict:
    event = {"name": name, "args": arguments, "ok": False}

    def reject(reason: str) -> dict:
        return {**event, "message": reason}

    if name not in TOOLS:
        return reject("Tool is outside the mock commerce allowlist.")
    try:
        args = TOOLS[name].model_validate(arguments)
    except ValidationError:
        return reject("Tool arguments do not match the expected fields.")
    if args.cart_id != context["cart_id"]:
        return reject("Cart ID does not match this call.")

    if name == "send_checkout_link":
        if args.discount_percent != context["discount_percent"]:
            return reject("Discount must match the merchant-approved UPI offer.")
        if args.amount != Decimal(context["price"]["upi"]):
            return reject("Amount must match the server UPI total.")
    if name == "confirm_cod_order" and args.amount != Decimal(context["price"]["cod"]):
        return reject("Amount must match the server COD total.")
    if not agreed(name, latest_shopper_turn, offer):
        return reject("The latest caller turn does not confirm this action.")

    if name == "send_checkout_link":
        card = {
            "kind": "checkout", "cart_id": args.cart_id,
            "amount": context["price"]["upi"], "savings": context["price"]["savings"],
            "discount_percent": args.discount_percent,
            "url": f"https://checkout.example/upi/{args.cart_id}",
        }
        message = "Mock UPI checkout created."
    elif name == "confirm_cod_order":
        card = {"kind": "cod", "cart_id": args.cart_id, "amount": context["price"]["cod"]}
        if args.verified_address_landmark:
            if args.verified_address_landmark.casefold() not in latest_shopper_turn.casefold():
                return reject("The caller has not verified this landmark.")
            card["landmark"] = args.verified_address_landmark
        message = "Mock COD order confirmed."
    else:
        card = {"kind": "callback", "cart_id": args.cart_id}
        if args.delay_minutes is not None:
            card["delay_minutes"] = args.delay_minutes
        if args.reason:
            card["reason"] = args.reason
        message = "Mock callback queued."
    return {**event, "ok": True, "message": message, "card": card}


def checkout_call(context: dict) -> dict:
    return {"name": "send_checkout_link", "args": {
        "cart_id": context["cart_id"], "amount": context["price"]["upi"],
        "discount_percent": context["discount_percent"],
    }}


def cod_call(context: dict) -> dict:
    return {"name": "confirm_cod_order", "args": {
        "cart_id": context["cart_id"], "amount": context["price"]["cod"],
    }}


def callback_call(context: dict) -> dict:
    return {"name": "schedule_callback", "args": {"cart_id": context["cart_id"]}}
