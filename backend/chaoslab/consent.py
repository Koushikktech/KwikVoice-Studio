"""Recognize direct requests and short answers to a single, named offer."""

import re
import unicodedata

# Full-turn matches keep negations, hypotheticals and reported speech out of the action path.
LINK = r"(?:(?:upi|யூபிஐ|యూపీఐ|ಯುಪಿಐ|യുപിഐ) )?(?:checkout )?(?:link|लिंक|லிங்க்|லிங்கை|இணைப்பை|లింక్|లింకు|ಲಿಂಕ್|ಲಿಂಕನ್ನು|ലിങ്ക്)"
SEND = (
    r"bhej(?:o| do| dijiye)|भेजो|भेज दो|भेज दीजिए|அனுப்பு(?:ங்க|ங்கள்)?|அனுப்பவும்|anuppu(?:nga)?|"
    r"పంపు|పంపండి|పంపించండి|pampu|pampandi|ಕಳಿಸಿ|ಕಳುಹಿಸಿ|kalisi|kaluhisi|"
    r"അയക്കൂ|അയയ്ക്കൂ|അയക്കുക|അയച്ചു തരൂ|ayakku"
)
OBJECT_COD = r"(?:cod|cash on delivery)(?: order)?"
CALLBACK = r"(?:a |the )?(?:callback|call back)"
DIRECT = {
    "send_checkout_link": (
        rf"(?:send|share|text) (?:me )?(?:the |a |my )?{LINK}(?: (?:to me|on whatsapp))?",
        rf"(?:upi (?:वाला|wala) (?:चेकआउट|checkout) )?{LINK}(?: (?:(?:मेरे )?(?:whatsapp|व्हाट्सऐप|व्हाट्सएप) पर|(?:mere )?whatsapp (?:pe|par)|on whatsapp))? (?:{SEND})",
        r"(?:pay|i(?:'ll| will) pay) (?:by|with|via) upi",
    ),
    "confirm_cod_order": (
        rf"confirm (?:the |my )?{OBJECT_COD}", rf"{OBJECT_COD} (?:confirm(?: kar do)?|kar do)",
        rf"{OBJECT_COD} (?:confirm |கன்ஃபார்ம் |కన్ఫర్మ్ |ಕನ್ಫರ್ಮ್ |കൺഫേം )(?:பண்ணுங்க|செய்யுங்கள்|చేయండి|ಮಾಡಿ|ചെയ്യൂ)",
        r"(?:cod|சிஓடி|సిఓడి|ಸಿಒಡಿ|സിഒഡി) (?:ஆர்டரை உறுதிப்படுத்துங்கள்|ఆర్డర్ నిర్ధారించండి|ಆರ್ಡರ್ ದೃಢೀಕರಿಸಿ|ഓർഡർ സ്ഥിരീകരിക്കൂ)",
    ),
    "schedule_callback": (
        r"call me back(?: later)?", rf"schedule {CALLBACK}", r"callback (?:kar do|de do)",
        r"திரும்ப அழைக்கவும்|திரும்ப கூப்பிடுங்க|తిరిగి కాల్ చేయండి|ಮತ್ತೆ ಕರೆ ಮಾಡಿ|തിരിച്ചു വിളിക്കൂ|തിരിച്ച് വിളിക്കൂ",
    ),
}
YES = {"yes", "yes please", "sure", "go ahead", "haan", "हाँ", "ஆமாம்", "ஆம்", "అవును", "ಹೌದು", "അതെ"}
OFFERS = {
    "send_checkout_link": (r"(?:(?:shall|should|may|can) i|would you like me to) send (?:you )?(?:the |a )?(?:upi |checkout )*link", r"(?:upi )?link bhej doon", r"லிங்க் அனுப்பவா|లింక్ పంపనా|ಲಿಂಕ್ ಕಳುಹಿಸಲೇ|ലിങ്ക് അയക്കട്ടെ"),
    "confirm_cod_order": (rf"(?:shall|should|may|can) i confirm (?:your |the )?{OBJECT_COD}",
                          r"cod (?:ஆர்டரை உறுதிப்படுத்தவா|ఆర్డర్ నిర్ధారించనా|ಆರ್ಡರ್ ದೃಢೀಕರಿಸಲೇ|ഓർഡർ സ്ഥിരീകരിക്കട്ടെ)",),
    "schedule_callback": (rf"(?:would you like|shall i schedule|may i schedule) {CALLBACK}",
                          r"திரும்ப அழைக்கவா|తిరిగి కాల్ చేయనా|ಮತ್ತೆ ಕರೆ ಮಾಡಲೇ|തിരിച്ചു വിളിക്കട്ടെ",),
}


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold().replace("’", "'")
    return " ".join(text.strip().strip(".!?।").strip().split())


def offered_action(reply: str) -> str | None:
    # Use only the final question, and never carry an offer across a second caller turn.
    if not reply.rstrip().endswith("?") or reply.count("?") != 1:
        return None
    question = normalized(re.split(r"[.!।]", reply)[-1])
    return next((tool for tool, patterns in OFFERS.items()
                 if any(re.fullmatch(pattern, question) for pattern in patterns)), None)


def agreed(tool: str, latest_shopper_turn: str, offer: str | None = None) -> bool:
    text = normalized(latest_shopper_turn)
    if tool not in DIRECT:
        return False
    if text in YES:
        return tool == offer
    if text in {"send it", "send it please", "bhej do"}:
        return tool == offer == "send_checkout_link"
    text = re.sub(r"^(?:yes|haan|हाँ|okay|sure)[, ]+", "", text)
    text = re.sub(r"^(?:please |can you |could you |would you |தயவுசெய்து |எனக்கு |దయచేసి |నాకు |ದಯವಿಟ್ಟು |ನನಗೆ |ദയവായി |എനിക്ക് )+", "", text)
    text = text.removesuffix(" please")
    return any(re.fullmatch(pattern, text) for pattern in DIRECT[tool])
