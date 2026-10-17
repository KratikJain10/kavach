#!/usr/bin/env python3
# Instant scam signals: phrases that Indian scam calls almost always use.
#   python rules.py "आप डिजिटल अरेस्ट में हैं"
#   python rules.py samples/scam_hi.wav          (transcribes first)

import re
import sys

# pattern -> (weight, regex). The regexes include the misspellings whisper actually produces on
# speaker-phone audio (e.g. ट्रांसपर, दिजिटल, खादे, पुलीस) and romanized Hindi (bijli, turant, bhej).
RULES = {
    "digital_arrest": (40, r"digital\s*arrest|[दड][िी]ज[िी]टल\s*अरेस्ट|अरेस्ट|arrest\s*warrant|गिरफ़?्तार|giraft?aar|वारंट|warrant"),
    "otp_pin":        (35, r"\botp\b|ओटीपी|\bpin\b|पिन\s*(नंबर|कोड)?|\bcvv\b"),
    "remote_app":     (35, r"any\s*desk|team\s*viewer|screen\s*share|एनी\s*डेस्क|स्क्रीन\s*शेयर"),
    "money_transfer": (25, r"ट्रा[ंन]्?स[फप]र|transfer|पैसे\s*(भेज|डाल|ट्रा)|\bupi\b|यूपीआई|safe\s*account|ख[ाा][तद]े\s*में\s*पैसे|paise?\s*(bhej|daal)|bhej\s*(do|de|dijiye)"),
    "secrecy":        (25, r"(किसी\s*को|घर\s*में).{0,12}मत\s*बत|don'?t\s*tell\s*any|मत\s*बताना|kisi\s*ko\s*(bhi\s*)?mat\s*bata"),
    "fake_authority": (20, r"\bcbi\b|सीबीआई|पु[लर][िी]स|police|crime\s*branch|साइबर\s*[क्रप्र]+ाइम|customs|कस्टम|narcotics|नारकोटिक्स|\bed\b|ट्राई|\btrai\b|आरबीआई|\brbi\b"),
    "courier_drugs":  (20, r"[पफव]ार्?स[लन]|parcel|courier|कूरियर|fedex|फेडेक्स|ड्रग्स|drugs|[टद्र]्?रक्स"),
    "electricity":    (30, r"बिजली|bijli|electricity|light\s*(cut|kat|कट)|(कनेक्शन|connection)\s*(कट|बंद|kat|cut|band)"),
    "prize":          (20, r"lottery|लॉटरी|prize|इनाम|\bkbc\b|जीत[ाे]\s*है"),
    "kyc_bank":       (15, r"\bkyc\b|केवाईसी|account\s*(block|band|बंद)|खाता\s*(बंद|ब्लॉक)"),
    "aadhaar":        (10, r"aadha?a?r|आ[धद]ार"),
    "urgency":        (10, r"तु[रर][ंत]त|turant|immediately|right\s*now|अभी\s*के\s*अभी|abhi\s*ke\s*abhi|\d+\s*(घंटे|ghante)"),
}
PATTERNS = list(RULES)
# Signals that only scams use. Money, urgency and secrecy alone also fit a friend borrowing money,
# so without at least one of these a call can be "suspicious" but never "scam".
TRICKS = {"digital_arrest", "otp_pin", "remote_app", "fake_authority", "courier_drugs", "electricity",
          "prize", "kyc_bank"}
_COMPILED = {k: (w, re.compile(rx, re.IGNORECASE)) for k, (w, rx) in RULES.items()}


def find(text):
    """Return {pattern: phrase that matched} for every rule the text triggers."""
    hits = {}
    for name, (_, rx) in _COMPILED.items():
        m = rx.search(text)
        if m:
            hits[name] = m.group(0)
    return hits


def score(hits):
    """Risk 0-100: each signal adds its weight once. Two or three strong signals = scam."""
    return min(100, sum(_COMPILED[p][0] for p in hits))


if __name__ == "__main__":
    arg = " ".join(sys.argv[1:])
    if arg.endswith(".wav"):
        import transcribe
        lines = []
        transcribe.from_file(arg, lambda line, _: lines.append(line))
        arg = " ".join(lines)
    print(arg)
    hits = find(arg)
    for p, phrase in hits.items():
        print(f"  • {p:<15} “{phrase}”")
    print(f"risk {score(hits)}")
