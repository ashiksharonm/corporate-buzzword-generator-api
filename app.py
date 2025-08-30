"""
Corporate Buzzword Generator API — FastAPI

What it does
------------
Polishes raw text into corporate-friendly messages and creates ready-to-send templates
(e.g., WFH requests, meeting pings, status updates) with different tones and mediums.

Designed to be listed on RapidAPI. Includes optional RapidAPI proxy header validation.

How to run locally
------------------
1) Create a virtual env and install deps:  
   pip install fastapi uvicorn pydantic[dotenv] python-multipart

2) Run the server:  
   uvicorn app:app --host 0.0.0.0 --port 8000

3) Open docs at: http://localhost:8000/docs

Environment variables (optional)
--------------------------------
- PROXY_SECRET: If set, incoming requests must include header X-RapidAPI-Proxy-Secret matching this value.
- API_TITLE, API_DESCRIPTION: Override metadata shown in OpenAPI / RapidAPI docs.

Production tips
---------------
- Use a production server (e.g., uvicorn with workers via Gunicorn):  
  gunicorn -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000 app:app
- Add caching in front (Cloudflare) if traffic grows.

License: MIT (adjust as you prefer).
"""
from __future__ import annotations

import os
import random
import re
from typing import List, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Depends, Query
from pydantic import BaseModel, Field

# -----------------------------
# App metadata (shows up in docs)
# -----------------------------
API_TITLE = os.getenv("API_TITLE", "Corporate Buzzword Generator API")
API_DESCRIPTION = os.getenv(
    "API_DESCRIPTION",
    "Turn raw text into polished corporate messages with selectable tone, length, and medium. "
    "Great for Slack/Teams/Email, WFH requests, and meeting updates."
)

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version="1.0.0",
    contact={
        "name": "Your Name / Org",
        "url": "https://your-domain.example",  # replace before publishing
        "email": "support@your-domain.example",  # replace before publishing
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# -----------------------------
# RapidAPI proxy header validation (optional but recommended)
# -----------------------------
PROXY_SECRET = os.getenv("PROXY_SECRET")


def require_proxy_secret(x_rapidapi_proxy_secret: Optional[str] = Header(default=None, alias="X-RapidAPI-Proxy-Secret")):
    """Require the RapidAPI proxy secret if PROXY_SECRET is set.

    When you publish on RapidAPI, under *Security* tab you'll see a Proxy Secret.
    Set PROXY_SECRET env var with that value and this dependency will validate it.
    """
    if PROXY_SECRET:
        if not x_rapidapi_proxy_secret:
            raise HTTPException(status_code=401, detail="Missing X-RapidAPI-Proxy-Secret header")
        if x_rapidapi_proxy_secret != PROXY_SECRET:
            raise HTTPException(status_code=401, detail="Invalid X-RapidAPI-Proxy-Secret header")
    # If PROXY_SECRET is not set, allow all.


# -----------------------------
# Models
# -----------------------------
Tone = Literal[
    "formal",
    "casual",
    "executive",
    "empathetic",
    "assertive",
    "friendly",
    "persuasive",
]

Medium = Literal["email", "slack", "teams", "whatsapp", "text", "doc"]

Length = Literal["short", "medium", "long"]

Locale = Literal["US", "IN", "UK", "AU", "SG", "Generic"]


class PolishRequest(BaseModel):
    text: str = Field(..., description="Raw content or bullet points. Use newline for bullets.")
    tone: Tone = Field("formal")
    medium: Medium = Field("slack")
    length: Length = Field("short")
    locale: Locale = Field("Generic")
    suggestions: int = Field(3, ge=1, le=8, description="How many alternative phrasings to return.")
    add_subject: bool = Field(False, description="If true and medium=email, include subject suggestions.")
    include_bullets: bool = Field(False, description="If true, include a concise bullet list of key points.")


class MessageVariant(BaseModel):
    subject: Optional[str] = None
    message: str


class PolishResponse(BaseModel):
    variants: List[MessageVariant]
    meta: dict


class BuzzwordifyRequest(BaseModel):
    text: str
    intensity: int = Field(2, ge=0, le=3, description="0 = minimal jargon, 3 = maximum corporatese")


class BuzzwordifyResponse(BaseModel):
    original: str
    transformed: str


class ReplySuggestionsRequest(BaseModel):
    incoming: str
    style: Literal["neutral", "positive", "pushback", "clarify", "acknowledge"] = "neutral"
    medium: Medium = "slack"
    suggestions: int = Field(3, ge=1, le=6)


class ReplySuggestionsResponse(BaseModel):
    replies: List[str]


# -----------------------------
# Phrase banks & templates (extend/modify to taste)
# -----------------------------
SIGN_OFF = {
    "email": [
        "Best regards,",
        "Kind regards,",
        "Thanks,",
        "Sincerely,",
        "Warm regards,",
    ],
    "slack": [
        "Thanks!",
        "Appreciate it!",
        "Cheers!",
        "— thanks",
    ],
    "teams": [
        "Thanks!",
        "Appreciated.",
        "Cheers!",
    ],
    "whatsapp": [
        "Thanks!",
        "Much appreciated.",
        "Cheers!",
    ],
    "text": ["Thanks!", "Appreciate it."],
    "doc": [""],
}

OPENERS = {
    "formal": [
        "Hope you are doing well.",
        "I wanted to reach out regarding the following.",
        "Following up on the item below.",
        "Sharing a quick update.",
    ],
    "casual": [
        "Quick update:",
        "Heads up—",
        "FYI—",
        "Ping on this:",
    ],
    "executive": [
        "Executive summary:",
        "At a glance:",
        "Top line:",
        "Key call-outs:",
    ],
    "empathetic": [
        "I understand this is time-sensitive.",
        "Appreciate the effort here.",
        "Thanks for your patience—",
        "Completely understand the context.",
    ],
    "assertive": [
        "We need a decision to unblock progress.",
        "Action required to stay on track.",
        "To hit our target, we need the following.",
        "Flagging a blocker:",
    ],
    "friendly": [
        "Quick one 🙂",
        "Hope your day’s going well!",
        "Just checking in—",
        "Sharing a quick note—",
    ],
    "persuasive": [
        "Here’s why this approach works:",
        "The data strongly supports this.",
        "This will help us deliver faster with less risk.",
        "Recommended path forward:",
    ],
}

BUZZWORD_MAP_LEVELS = [
    # Level 0 (identity)
    {},
    # Level 1
    {
        r"help": "support",
        r"ask": "request",
        r"finish": "complete",
        r"start": "kick off",
        r"check": "review",
        r"talk": "sync",
        r"plan": "roadmap",
        r"fix": "resolve",
        r"problem": "issue",
        r"delay": "slippage",
        r"fast": "expedited",
        r"slow": "deprioritized",
        r"meet": "connect",
    },
    # Level 2
    {
        r"do": "execute",
        r"make": "build",
        r"try": "explore",
        r"change": "iterate",
        r"improve": "optimize",
        r"decide": "align on a decision",
        r"team": "cross-functional team",
        r"work together": "collaborate",
        r"because": "so that",
        r"goal": "north star",
        r"idea": "proposal",
    },
    # Level 3
    {
        r"use": "leverage",
        r"use (?!case)": "utilize",
        r"result": "outcome",
        r"plan": "strategic roadmap",
        r"meeting": "working session",
        r"deadline": "target date",
        r"notes?": "takeaways",
        r"OK": "actionable",
        r"good": "impactful",
        r"bad": "non-optimal",
        r"next": "forward-looking",
    },
]

EMAIL_SUBJECT_PREFIX = {
    "formal": ["Update:", "Request:", "Follow-up:", "Action needed:"],
    "executive": ["Summary:", "Heads-up:", "Decision needed:", "Risks & Next Steps:"],
    "assertive": ["Blocker:", "Decision required:", "Deadline risk:"],
    "empathetic": ["Appreciate your help:", "Thanks & quick ask:", "Thanks for the support:"],
    "casual": ["Quick update:", "Small ask:", "Heads-up:"],
    "friendly": ["Hey—quick one:", "Tiny ask:", "Quick sync?"],
    "persuasive": ["Proposal:", "Why this works:", "Recommended path:"],
}

LOCALE_FLAVOR = {
    "IN": {
        "politeness": [
            "Kindly let me know your thoughts.",
            "Please advise if this works for you.",
            "Requesting your approval to proceed.",
        ],
        "greetings": [
            "Hope you are doing well.",
            "Hope you’re keeping well.",
        ],
    },
    "US": {
        "politeness": [
            "Would love your feedback.",
            "Let me know if you have any questions.",
            "If you're good with this, I’ll proceed.",
        ],
        "greetings": [
            "Hope you're doing well.",
            "Hope your week is going well.",
        ],
    },
    "UK": {
        "politeness": [
            "Would you be happy to proceed?",
            "Grateful for your thoughts.",
            "Do let me know if that suits.",
        ],
        "greetings": [
            "Trust you're well.",
            "Hope all's well.",
        ],
    },
    "Generic": {"politeness": [], "greetings": []},
    "AU": {"politeness": ["Keen to hear your thoughts."], "greetings": ["Hope you’re well."]},
    "SG": {"politeness": ["Appreciate your advice."], "greetings": ["Hope you’re well."]},
}


def pick(items: List[str]) -> str:
    return random.choice(items) if items else ""


def to_bullets(text: str) -> List[str]:
    # Split on newlines or ";" or "- " and clean
    raw = re.split(r"\n|;|\s-\s", text)
    bullets = [x.strip(" -*\t") for x in raw if x and x.strip()]
    # De-duplicate while preserving order
    seen = set()
    deduped = []
    for b in bullets:
        if b.lower() not in seen:
            seen.add(b.lower())
            deduped.append(b)
    return deduped[:8]


def apply_buzzwords(s: str, intensity: int) -> str:
    if intensity <= 0:
        return s
    out = s
    for lvl in range(1, intensity + 1):
        for pat, rep in BUZZWORD_MAP_LEVELS[lvl].items():
            out = re.sub(rf"\b{pat}\b", rep, out, flags=re.IGNORECASE)
    return out


def make_subject(tone: Tone, bullets: List[str]) -> str:
    prefix = pick(EMAIL_SUBJECT_PREFIX.get(tone, ["Update:"]))
    core = bullets[0] if bullets else "Update"
    # Keep it concise
    core = re.sub(r"^[-•\s]+", "", core)
    core = re.sub(r"\.$", "", core)
    return f"{prefix} {core[:72]}".strip()


def sign_off(medium: Medium) -> str:
    return pick(SIGN_OFF.get(medium, [""]))


def compose_message(
    text: str,
    tone: Tone,
    medium: Medium,
    length: Length,
    locale: Locale,
    include_bullets: bool,
    add_subject: bool,
) -> MessageVariant:
    bullets = to_bullets(text)
    opener = pick(OPENERS[tone])

    locale_bits = LOCALE_FLAVOR.get(locale, LOCALE_FLAVOR["Generic"])
    greeting = pick(locale_bits.get("greetings", []))
    politeness = pick(locale_bits.get("politeness", []))

    # Body assembly
    body_parts: List[str] = []

    if medium in ("email", "doc") and greeting:
        body_parts.append(greeting)

    if opener:
        body_parts.append(opener)

    # Bullet summary if requested or if executive tone with medium email/doc
    if include_bullets or (tone == "executive" and medium in ("email", "doc")):
        if bullets:
            body_parts.append("\n".join([f"• {b}" for b in bullets[:5]]))

    # Single-line summary
    summary = " ".join(bullets[:2]) if bullets else text
    if length == "short":
        core = f"{summary}."
    elif length == "medium":
        core = (
            f"{summary}. Requesting your input on the above so we can proceed without delay."
        )
    else:  # long
        core = (
            f"{summary}. Here's the context: {', '.join(bullets[2:5]) if len(bullets)>2 else 'see above'}. "
            f"Next steps: we'll align on owners & timelines after your feedback."
        )
    body_parts.append(core)

    if politeness:
        body_parts.append(politeness)

    s_off = sign_off(medium)
    if s_off:
        body_parts.append(s_off)

    msg = "\n\n".join([p for p in body_parts if p])

    subj = make_subject(tone, bullets) if (medium == "email" and add_subject) else None
    return MessageVariant(subject=subj, message=msg)


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/", tags=["meta"]) 
def root():
    return {
        "name": API_TITLE,
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/polish", "/buzzwordify", "/reply-suggestions", "/phrases", "/health"],
    }


@app.get("/health", tags=["meta"]) 
def health():
    return {"status": "ok"}


@app.post("/polish", response_model=PolishResponse, tags=["compose"], dependencies=[Depends(require_proxy_secret)])
def polish(req: PolishRequest):
    """Return multiple polished variants according to tone/medium/length/locale."""
    random.seed(len(req.text) + req.suggestions)  # stable-ish randomness
    variants: List[MessageVariant] = []
    for _ in range(req.suggestions):
        v = compose_message(
            text=req.text,
            tone=req.tone,
            medium=req.medium,
            length=req.length,
            locale=req.locale,
            include_bullets=req.include_bullets,
            add_subject=req.add_subject,
        )
        # Add slight variation by applying buzzwords lightly for some variants
        if random.random() < 0.5:
            v.message = apply_buzzwords(v.message, 1)
            if v.subject:
                v.subject = apply_buzzwords(v.subject, 1)
        variants.append(v)

    return {
        "variants": variants,
        "meta": {
            "tone": req.tone,
            "medium": req.medium,
            "length": req.length,
            "locale": req.locale,
            "suggestions": req.suggestions,
        },
    }


@app.post("/buzzwordify", response_model=BuzzwordifyResponse, tags=["transform"], dependencies=[Depends(require_proxy_secret)])
def buzzwordify(req: BuzzwordifyRequest):
    transformed = apply_buzzwords(req.text, req.intensity)
    return {"original": req.text, "transformed": transformed}


@app.post("/reply-suggestions", response_model=ReplySuggestionsResponse, tags=["compose"], dependencies=[Depends(require_proxy_secret)])
def reply_suggestions(req: ReplySuggestionsRequest):
    style_map = {
        "neutral": [
            "Thanks for the update—got it.",
            "Acknowledged. I’ll keep you posted.",
            "Noted, thanks.",
        ],
        "positive": [
            "This looks great—thanks for pushing it forward!",
            "Nice progress—appreciate the momentum.",
            "Awesome—thanks for the clarity!",
        ],
        "pushback": [
            "Thanks—timeline is tight. Can we prioritize the critical path and revisit the rest next sprint?",
            "Appreciate it. Given constraints, proposing we de-scope X to hit the target date—thoughts?",
            "Understood. For feasibility, can we align on the must-haves first?",
        ],
        "clarify": [
            "Thanks—could you clarify the owner for the next step?",
            "Helpful. What’s the expected date for the handoff?",
            "Got it—what’s the definition of done here?",
        ],
        "acknowledge": [
            "Received, thanks.",
            "Acknowledged—will do.",
            "Noted—appreciate it.",
        ],
    }

    base = style_map.get(req.style, style_map["neutral"])
    n = min(req.suggestions, len(base))
    replies = base[:n]

    # Medium-savvy tweaks
    if req.medium in ("slack", "teams"):
        replies = [r.replace("—", " - ") for r in replies]
    return {"replies": replies}


@app.get("/phrases", tags=["reference"], dependencies=[Depends(require_proxy_secret)])
def phrases(context: Optional[str] = Query(default=None, description="e.g., 'one_on_one', 'status', 'follow_up'")):
    base = {
        "one_on_one": [
            "Agenda: updates, blockers, next sprint priorities.",
            "I’d appreciate feedback on X and growth areas.",
            "What would make the biggest impact if I focused on it this week?",
        ],
        "status": [
            "Green on scope; amber on timeline; risk on dependency Y.",
            "On track overall; one risk identified—mitigation in progress.",
            "Blocked on approval; ETA slips by 2 days without decision.",
        ],
        "follow_up": [
            "Looping back on the below—any update?",
            "Gentle nudge in case this got buried.",
            "Re-surfacing this for visibility—appreciate a quick look.",
        ],
        "wfh": [
            "Requesting WFH on <dates>—deliverables unaffected.",
            "WFH next week due to personal commitment; coverage planned.",
            "Seeking approval for remote work on <date>; meetings unaffected.",
        ],
    }

    if context and context in base:
        return {context: base[context]}
    return base


# ------------- End of file -------------
