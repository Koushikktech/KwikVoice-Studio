from copy import deepcopy

import pytest

from chaoslab.merchant import PRESETS, MerchantInput, compile_merchant, greeting_name, lint, word_count


@pytest.mark.parametrize(("raw", "expected"), [
    ("ROHIT_SHARMA_99", "Rohit"),
    ("  MS. Aanya   Sharma  ", "Aanya"),
    ("स्नेहा_शर्मा", "स्नेहा"),
    ("_99_", ""),
])
def test_greeting_name(raw, expected):
    assert greeting_name(raw) == expected


def test_shopify_serum_and_spoken_prices():
    result = compile_merchant(MerchantInput.model_validate(PRESETS[0]))
    context = result["context"]
    assert context["products"] == ["DermPure Niacinamide Serum"]
    assert context["first_name"] == "Rohit"
    assert context["spoken"]["cod"] == "seven hundred and forty nine rupees"
    assert context["spoken"]["upi"] == "six hundred and twenty nine rupees"
    assert context["spoken"]["savings"] == "one hundred and twenty rupees"


def test_edited_product_uses_edited_name():
    payload = deepcopy(PRESETS[0])
    payload["cart"]["items"][0]["title"] = "Clay & Zinc Mask - 80g [SKU-DP-8821-B] (Pack of 2)"
    ctx = compile_merchant(MerchantInput.model_validate(payload))["context"]
    assert ctx["products"] == ["Clay and Zinc Mask"]


def test_lint_expands_only_spoken_examples():
    instruction = "Never exceed 10%. Use Cash on Delivery or UPI."
    raw = instruction + "\nAgent: **COD** costs ₹50. UPI & cards get 10% off. [SKU-DP-8821-B]"
    report = lint(raw)
    assert {d["line"] for d in report["diagnostics"]} == {2}
    assert report["fixed_prompt"].startswith(instruction + "\n")
    assert "Cash on Delivery costs fifty rupees" in report["fixed_prompt"]
    assert "UPI and cards get ten percent off" in report["fixed_prompt"]
    assert "8821" not in report["fixed_prompt"]
    assert lint(report["fixed_prompt"])["score"] == 100


def test_malformed_currency_remains_a_diagnostic():
    assert lint("Agent: That costs ₹,,")["diagnostics"][0]["code"] == "raw_symbol"


def test_hindi_word_count_keeps_vowel_marks_with_letters():
    assert word_count("आपके पैसे कहाँ गए?") == 4


def test_flat_checkout_from_the_brief_compiles_without_reshaping():
    raw = {
        "brand_name": "DermPure Labs", "customer_name": "ROHIT_SHARMA_99",
        "product_title": "DermPure 10% Niacinamide + Zinc Serum - 30ml [SKU-DP-8821-B] (Pack of 1)",
        "cart_value_inr": 699, "cod_fee_inr": 50, "failed_coupon": "FRESH20",
        "max_allowed_discount_pct": 10, "upi_waives_cod_fee": True,
    }
    result = compile_merchant(MerchantInput.model_validate(raw))
    assert result["context"]["products"] == ["DermPure Niacinamide Serum"]
    assert result["context"]["price"]["upi"] == "629.00"
    assert "DermPure Labs" in result["prompt"]


def test_native_transcript_accepts_a_hinglish_link_request_and_respects_negation():
    from chaoslab.commerce import agreed

    assert agreed("send_checkout_link", "UPI वाला चेकआउट लिंक मेरे WhatsApp पर भेज दो।")
    assert not agreed("send_checkout_link", "UPI वाला चेकआउट लिंक मत भेजो।")
    assert not agreed("send_checkout_link", "UPI वाला चेकआउट लिंक नहीं चाहिए।")


@pytest.mark.parametrize(("request_text", "refusal"), [
    ("UPI லிங்க் அனுப்புங்க", "லிங்க் அனுப்ப வேண்டாம்"),
    ("లింక్ పంపండి", "లింక్ పంపవద్దు"),
    ("ಲಿಂಕ್ ಕಳುಹಿಸಿ", "ಲಿಂಕ್ ಕಳುಹಿಸಬೇಡಿ"),
    ("ലിങ്ക് അയക്കൂ", "ലിങ്ക് അയക്കേണ്ട"),
    ("Link anuppunga", "Link anuppa vendam"),
    ("UPI wala checkout link mere WhatsApp par bhej do.", "UPI wala checkout link abhi mat bhej do."),
    ("Yes, send me the link", "Yes, how much would UPI cost?"),
])
def test_only_direct_requests_authorize_checkout(request_text, refusal):
    from chaoslab.consent import agreed

    assert agreed("send_checkout_link", request_text)
    assert not agreed("send_checkout_link", refusal)


def test_short_answers_apply_only_to_an_unambiguous_offer():
    from chaoslab.consent import agreed, offered_action

    offer = offered_action("UPI is cheaper. Shall I send the link?")
    assert agreed("send_checkout_link", "ஆம்", offer)
    assert not agreed("confirm_cod_order", "yes", offer)
    assert not agreed("send_checkout_link", "yes", offered_action("Would you like to hear the total?"))
    assert not agreed("send_checkout_link", "yes", offered_action("Shall I send a link or confirm your order?"))


def test_model_prompt_excludes_only_the_fixture_sample():
    from chaoslab.merchant import model_prompt, LONG_EXAMPLE

    prompt = compile_merchant(MerchantInput.model_validate(PRESETS[0]))["prompt"]
    actual = model_prompt(prompt + "\nKeep this merchant edit.")
    assert LONG_EXAMPLE in prompt and LONG_EXAMPLE not in actual
    assert "Malayalam" in actual and actual.endswith("Keep this merchant edit.")
