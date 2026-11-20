import re
import unicodedata
from copy import deepcopy
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Flow = Literal["cart-recovery", "cod-confirmation"]
Money = Annotated[Decimal, Field(ge=0, le=999999, max_digits=8, decimal_places=2)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Item(InputModel):
    title: Text
    sku: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,48}$")]
    quantity: Annotated[int, Field(strict=True, ge=1, le=20)]
    price: Annotated[Money, Field(gt=0)]


class Cart(InputModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,48}$")]
    customer: Text
    phone: Annotated[str, StringConstraints(pattern=r"^\+91 00000 [0-9]{5}$")]
    coupon: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{1,20}$")]
    items: list[Item] = Field(min_length=1, max_length=8)
    cod_fee: Money


class Fact(InputModel):
    question: Text
    answer: Text


class Merchant(InputModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]
    name: Text
    tone: Text
    locale: Literal["mirror"]
    max_discount_percent: Annotated[int, Field(strict=True, ge=0, le=30)]
    waive_cod_fee_on_upi: bool
    rounding: Literal["whole_rupee_down", "nearest_paise"]
    faq: list[Fact] = Field(min_length=1, max_length=8)


class CheckoutFixture(InputModel):
    brand_name: Text
    customer_name: Text
    product_title: Text
    cart_value_inr: Annotated[Money, Field(gt=0)]
    cod_fee_inr: Money
    failed_coupon: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{1,20}$")]
    max_allowed_discount_pct: Annotated[int, Field(strict=True, ge=0, le=30)]
    upi_waives_cod_fee: bool
    flow: Flow = "cart-recovery"


class MerchantInput(InputModel):
    merchant: Merchant
    cart: Cart
    flow: Flow = "cart-recovery"

    @model_validator(mode="before")
    @classmethod
    def expand_checkout_fixture(cls, value):
        if not isinstance(value, dict) or "brand_name" not in value:
            return value
        fixture = CheckoutFixture.model_validate(value)
        preset = next(
            (p for p in PRESETS if fixture.brand_name.casefold().startswith(p["merchant"]["id"])),
            None,
        )
        if preset is None:
            raise ValueError("Choose a known merchant or supply a merchant and cart configuration.")
        source = deepcopy(preset)
        source["merchant"].update(
            name=fixture.brand_name, max_discount_percent=fixture.max_allowed_discount_pct,
            waive_cod_fee_on_upi=fixture.upi_waives_cod_fee,
        )
        sku_match = re.search(r"\[SKU-([A-Z0-9_-]+)\]", fixture.product_title, re.I)
        item = {
            "title": fixture.product_title, "price": fixture.cart_value_inr,
            "quantity": 1, "sku": sku_match[1] if sku_match else "DEMO-ITEM",
        }
        source["cart"].update(customer=fixture.customer_name, cod_fee=fixture.cod_fee_inr,
                             coupon=fixture.failed_coupon, items=[item])
        source["flow"] = fixture.flow
        return source


PRESETS = [
    {
        "merchant": {
            "id": "dermpure", "name": "DermPure", "tone": "Calm and matter-of-fact.",
            "locale": "mirror", "max_discount_percent": 10, "waive_cod_fee_on_upi": True,
            "rounding": "whole_rupee_down",
            "faq": [
                {"question": "What size is the serum?", "answer": "The serum comes in a thirty millilitre bottle."},
                {"question": "When will it dispatch?", "answer": "Orders dispatch within two business days."},
            ],
        },
        "cart": {
            "id": "dp-1042", "customer": "ROHIT_SHARMA_99", "phone": "+91 00000 01042",
            "coupon": "FRESH20", "cod_fee": "50.00",
            "items": [{"title": "DermPure 10% Niacinamide + Zinc Serum - 30ml [SKU-DP-8821-B] (Pack of 1)",
                       "sku": "DP-8821-B", "quantity": 1, "price": "699.00"}],
        },
    },
    {
        "merchant": {
            "id": "kicksdrop", "name": "KicksDrop", "tone": "Direct and relaxed.",
            "locale": "mirror", "max_discount_percent": 8, "waive_cod_fee_on_upi": True,
            "rounding": "nearest_paise",
            "faq": [{"question": "What size is in my cart?", "answer": "Your Runner Low is a UK size eight."}],
        },
        "cart": {
            "id": "kd-2308", "customer": "  MR. Kabir   Rao ", "phone": "+91 00000 02308",
            "coupon": "DROP25", "cod_fee": "65.00",
            "items": [{"title": "Runner Low | Chalk / UK 8 | SKU: KD-RL-08",
                       "sku": "KD-RL-08", "quantity": 1, "price": "2499.50"}],
        },
    },
    {
        "merchant": {
            "id": "vedaroot", "name": "VedaRoot", "tone": "Warm and clear.",
            "locale": "mirror", "max_discount_percent": 5, "waive_cod_fee_on_upi": False,
            "rounding": "nearest_paise",
            "faq": [{"question": "How much tea is in a pack?", "answer": "Each pack contains twenty tea bags."}],
        },
        "cart": {
            "id": "vr-3104", "customer": "  DR. Meera   Iyer ", "phone": "+91 00000 03104",
            "coupon": "ROOT15", "cod_fee": "35.00",
            "items": [{"title": "Tulsi Mint Tea | 20 bags | SKU: VR-TM-20",
                       "sku": "VR-TM-20", "quantity": 2, "price": "349.00"}],
        },
    },
]

ENVIRONMENT = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True,
)
SHORT_EXAMPLE = "I can confirm the total and help with your checkout."
LONG_EXAMPLE = (
    "I can confirm the total for the items you selected today and then help you finish the checkout "
    "whenever you are ready to continue with me."
)
EXAMPLE_PREFIX = "Agent: "
WORD_TARGET = 18
WORD_LIMIT = 20

SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(number: int) -> str:
    if number < 20:
        return SMALL[number]
    if number < 100:
        return TENS[number // 10] + (f" {SMALL[number % 10]}" if number % 10 else "")
    for unit, name in [(10_000_000, "crore"), (100_000, "lakh"), (1_000, "thousand"), (100, "hundred")]:
        if number >= unit:
            quotient, rest = divmod(number, unit)
            words = f"{number_words(quotient)} {name}"
            if rest:
                link = " and " if rest < 100 else " "
                words += link + number_words(rest)
            return words
    raise ValueError("Expected a whole number.")


def spoken_money(amount: Decimal) -> str:
    rupees, paise = divmod(int(amount * 100), 100)
    speech = f"{number_words(rupees)} {'rupee' if rupees == 1 else 'rupees'}"
    if paise:
        speech += f" and {number_words(paise)} {'paisa' if paise == 1 else 'paise'}"
    return speech


def clean(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char if not unicodedata.category(char).startswith("C") else " " for char in value)
    return " ".join(value.split())


def word_count(value: str) -> int:
    # Combining marks belong to the preceding letter in Hindi.
    plain = "".join(ch for ch in value if unicodedata.category(ch)[0] != "M")
    return len(re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", plain, flags=re.UNICODE))


def greeting_name(value: str) -> str:
    words = re.sub(r"[\d_]+", " ", clean(value))
    words = re.sub(r"^(?:mr|ms|mrs|dr)\.?\s+", "", words.strip(), flags=re.I).split()
    if not words:
        return ""
    first = words[0].strip(".,-")
    if not any(char.isalpha() for char in first):
        return ""
    return first.title() if first.isupper() or first.islower() else first


SKU_TOKEN = re.compile(r"\[\s*SKU[^\]]*\]|\bSKU(?:\s*[:#-]\s*)[\w-]+\b", re.I)
PACK_OR_SIZE = re.compile(
    r"\(\s*pack of \d+\s*\)|(?:^|\s)\d+(?:\.\d+)?\s*(?:ml|mg|gm|kg|g|oz|litres?)\b", re.I
)


def spoken_product(item: Item) -> str:
    title = clean(item.title).split("|", 1)[0]
    title = SKU_TOKEN.sub(" ", title)
    title = re.sub(rf"(?<!\w){re.escape(item.sku)}(?!\w)", " ", title, flags=re.I)
    title = PACK_OR_SIZE.sub(" ", title)
    title = clean(title).strip(" -,;:[]()")
    # Use the merchant's short name only when both the SKU and title match its catalog.
    if item.sku == "DP-8821-B" and title == "DermPure 10% Niacinamide + Zinc Serum":
        return "DermPure Niacinamide Serum"
    title = PERCENT_PATTERN.sub(lambda m: f"{number_words(int(m[1]))} percent", title)
    title = re.sub(r"[+&/]", " and ", title)
    return clean(title).strip(" -,;:[]()")


def model_prompt(prompt: str) -> str:
    return re.sub(r"(?m)^Fixture QA sample \(excluded from model instructions\)\nAgent: [^\n]*\nEnd fixture QA sample$", "", prompt).strip()


def compile_merchant(source: MerchantInput, base_template: str | None = None) -> dict:
    merchant, cart = source.merchant, source.cart
    customer = greeting_name(cart.customer)
    names = [spoken_product(item) for item in cart.items]
    if not customer or not all(names) or not clean(merchant.name):
        raise ValueError("Enter a customer name, merchant name and product title with visible characters.")

    subtotal = sum(item.price * item.quantity for item in cart.items)
    cod = subtotal + cart.cod_fee
    discounted = subtotal * (100 - merchant.max_discount_percent) / 100
    if merchant.max_discount_percent:
        discounted = (
            discounted.quantize(Decimal("1"), rounding=ROUND_DOWN)
            if merchant.rounding == "whole_rupee_down"
            else discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    upi = discounted + (0 if merchant.waive_cod_fee_on_upi else cart.cod_fee)
    savings = cod - upi
    values = {"subtotal": subtotal, "cod_fee": cart.cod_fee, "cod": cod, "upi": upi, "savings": savings}
    context = {
        "merchant_name": clean(merchant.name), "tone": clean(merchant.tone),
        "first_name": customer, "products": names, "cart_id": cart.id,
        "price": {key: f"{value:.2f}" for key, value in values.items()},
        "spoken": {key: spoken_money(value) for key, value in values.items()},
        "discount_percent": merchant.max_discount_percent,
        "spoken_discount": f"{number_words(merchant.max_discount_percent)} percent",
        "waives_fee": merchant.waive_cod_fee_on_upi,
        "rounding": merchant.rounding,
        "coupon": cart.coupon, "phone": cart.phone,
        "items": [{"name": name, "quantity": item.quantity, "sku": item.sku}
                  for name, item in zip(names, cart.items, strict=True)],
        "faq": [{"question": clean(fact.question), "answer": clean(fact.answer)} for fact in merchant.faq],
        "flow": source.flow,
    }
    transforms = [
        {"field": "Customer greeting", "before": cart.customer, "after": customer},
        *({"field": item.sku, "before": item.title, "after": name}
          for name, item in zip(names, cart.items, strict=True)),
    ]
    environment = ENVIRONMENT
    if base_template is not None:
        environment = ENVIRONMENT.overlay(loader=ChoiceLoader([DictLoader({"base.jinja": base_template}), ENVIRONMENT.loader]))
    prompt = environment.get_template(f"{source.flow}.jinja").render(
        **context, long_example=LONG_EXAMPLE, target=WORD_TARGET, limit=WORD_LIMIT,
    )
    return {
        "raw": cart.model_dump(mode="json"),
        "sanitized": {
            "first_name": customer, "product_names": names, "cod_total_spoken": context["spoken"]["cod"],
            "upi_discounted_total_spoken": context["spoken"]["upi"],
            "total_upi_savings_spoken": context["spoken"]["savings"],
        },
        "context": context, "transformations": transforms, "prompt": prompt, "lint": lint(prompt),
    }


MONEY_PATTERN = re.compile(r"(?:₹\s*|(?:INR|Rs\.?)\s+)(\d[\d,]{0,13}(?:\.\d{1,2})?)", re.I)
PERCENT_PATTERN = re.compile(r"(?<![\w.])(\d{1,3})\s*%")
MARKDOWN_PATTERN = re.compile(r"(?<!\w)(?:[*_]{1,2})(?=\S)|(?<=\S)[*_]{1,2}(?!\w)|[\x60#]|^\s*[-+>]\s+")
UNRESOLVED = re.compile(r"\{\{|\}\}|\{%|%\}|\$\{[^}]*\}|<UNRESOLVED:[^>]*>")
SYMBOL = re.compile(r"[₹$€£%/&]|\b(?:COD|INR|SKU)\b|\bRs\.?\s+\d", re.I)


def lint(prompt: str) -> dict:
    diagnostics = []
    fixed_lines = []

    def report(line: int, code: str, message: str, fixable: bool = False) -> None:
        diagnostics.append({
            "line": line, "code": code, "message": message, "fixable": fixable,
            "severity": "error" if code == "unresolved_variable" else "warning",
        })

    for index, line in enumerate(prompt.split("\n"), 1):
        if UNRESOLVED.search(line):
            report(index, "unresolved_variable", "Resolve the template variable before running this prompt.")
        if line.lstrip().startswith(EXAMPLE_PREFIX):
            _, _, speech = line.partition(EXAMPLE_PREFIX)
            fixed = MONEY_PATTERN.sub(lambda m: spoken_money(Decimal(m[1].replace(",", ""))), speech)
            fixed = PERCENT_PATTERN.sub(lambda m: f"{number_words(int(m[1]))} percent", fixed)
            fixed = SKU_TOKEN.sub("", fixed)
            fixed = re.sub(r"\bCOD\b", "Cash on Delivery", fixed)
            fixed = re.sub(r"\bINR\b", "rupees", fixed)
            fixed = re.sub(r"\s*&\s*", " and ", fixed)
            if "://" not in fixed:
                fixed = re.sub(r"(?<=\w)/(?=\w)", " or ", fixed)
            if SYMBOL.search(speech):
                report(index, "raw_symbol", "Use spoken words for amounts and abbreviations. Remove stock codes.", fixed != speech)
            if MARKDOWN_PATTERN.search(speech):
                report(index, "markdown", "Remove formatting from the spoken line.", True)
                fixed = MARKDOWN_PATTERN.sub("", fixed)
            count = word_count(speech)
            if count > WORD_LIMIT:
                report(index, "monologue", f"Turn has {count} words. The limit is {WORD_LIMIT}.")
            elif count > WORD_TARGET:
                report(index, "word_target", f"Turn has {count} words. Aim for {WORD_TARGET}.")
            line = f"{line[:line.index(EXAMPLE_PREFIX)]}{EXAMPLE_PREFIX}{fixed}"
        fixed_lines.append(line)

    rule_ids = {
        "unresolved_variable": "UNBOUND_VARIABLE", "raw_symbol": "RAW_TTS_SYMBOLS",
        "markdown": "NO_MARKDOWN_IN_SPEECH", "monologue": "MONOLOGUE_RISK",
        "word_target": "TURN_WORD_LIMIT",
    }
    for diagnostic in diagnostics:
        diagnostic["rule"] = rule_ids[diagnostic["code"]]
        diagnostic["auto_fix"] = fixed_lines[diagnostic["line"] - 1] if diagnostic["fixable"] else None
    return {
        "diagnostics": diagnostics, "score": max(0, 100 - sum(
            5 if issue["code"] == "word_target" else 10 for issue in diagnostics
        )),
        "fixed_prompt": "\n".join(fixed_lines),
    }
