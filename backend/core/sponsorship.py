"""Read a job description and find statements about visa sponsorship.

Rules handle clear offers and refusals. AI suggestions must pass the same
evidence checks before we save them. Unclear wording stays marked for review.
Nothing here decides whether a candidate is legally eligible for a visa.
"""

import hashlib
import re
from datetime import datetime

STATUSES = {"mentioned", "conditional", "not_available", "not_specified"}
# Increase this version when changing rules so saved assessments are checked again.
CLASSIFIER_VERSION = "1"
# These patterns look for relevant words, refusals, offers, and restrictions.
INTEREST = re.compile(r"\b(?:visa|sponsor\w*|immigration|work permits?|h[- ]?1b)\b", re.I)
NEGATIVE = re.compile(
    r"\bno\s+(?:visa |work permit )?sponsorship\b|"
    r"\bwithout\s+(?:requiring\s+)?(?:current or future\s+)?(?:visa )?sponsorship\b|"
    r"\b(?:cannot|can't|unable to|not able to|do not|don't|does not|doesn't|will not|won't)\s+(?:currently\s+)?(?:offer|provide|support)\s+(?:(?:any|employment|visa|work permit|form of)\s+){0,4}sponsorship\b|"
    r"\b(?:cannot|can't|unable to|not able to|do not|don't|will not|won't)\s+(?:currently\s+)?sponsor\b(?=\s+(?:new work visas?|new visas?|work visas?|visas?|candidates|applicants|at this time|now)\b|[.!?]|$)|"
    r"\bsponsorship\s+(?:(?:is|will be)\s+)?(?:currently\s+)?(?:not available|not offered|unavailable|not provided|not possible|not an option)\b|"
    r"\bsponsorship\s+(?:is not|isn't|will not be|won't be|cannot be)\s+(?:available|offered|provided|supported)\b", re.I)
POSITIVE = re.compile(r"\b(?:offer|offers|provide|provides|providing|support|supports)\s+(?:(?:eligible candidates|candidates|employment|full|visa|work permit|with|for|this role)\s+){0,5}(?:visa sponsorship|work permit sponsorship)\b|\b(?:visa sponsorship|work permit sponsorship)\b.{0,45}\b(?:available|offered|provided|supported)\b|\b(?:we|company|employer)\s+(?:(?:can|will)\s+)?sponsor\s+(?:work\s+)?visas?\b", re.I)
CONDITIONAL = re.compile(r"\b(?:if|may|might|eligible|eligibility|depending|subject to|case.by.case|consider|considered|certain|selected|only|except|excluding|restricted|limited|not for|transfer\w*)\b", re.I)
TRANSFER = re.compile(r"\b(?:visa|h[- ]?1b)\b.{0,35}\btransfer\w*\b|\btransfer\w*\b.{0,35}\b(?:visa|h[- ]?1b)\b", re.I)
HISTORICAL = re.compile(r"\b(?:previously|historically|in the past|past sponsorship|used to|have sponsored|has sponsored)\b", re.I)
NOT_NEEDED = re.compile(r"\b(?:visa )?sponsorship\s+(?:is\s+)?(?:not required|not needed|unnecessary)\b|\b(?:do not|don't)\s+(?:require|need)\s+(?:visa )?sponsorship\b|\bno\s+(?:visa )?sponsorship\s+(?:is\s+)?(?:required|needed|restrictions|limitations)\b", re.I)


def normalize(value):
    """Make spacing and punctuation consistent when comparing two quotes."""
    return " ".join(value.replace("’", "'").replace("–", "-").split())


def sentences(description):
    """Split the description into sentences or lines, keeping their original words."""
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+|\n+", description or "") if part.strip()]


def sentence_status(sentence):
    """Classify one sentence, or return None when it does not give a clear answer.

    Check refusals and restrictions before accepting a positive statement.
    None means this sentence is not enough to classify the job.
    """
    value = normalize(sentence)
    # Not needing sponsorship is different from an employer refusing to offer it.
    if NOT_NEEDED.search(value):
        return None
    if re.search(r"\b(?:for other (?:roles|positions)|by (?:other|some) (?:employers|companies))\b", value, re.I):
        return None
    negative = bool(NEGATIVE.search(value) or re.search(r"\bnot for (?:this|the|our) (?:role|position|vacancy|job)\b|\bsponsorship\s+(?:is\s+)?never\s+(?:available|offered|provided|supported)\b", value, re.I))
    # Past sponsorship does not prove that this vacancy offers it today.
    if HISTORICAL.search(value) and not negative:
        return None
    positive = bool(POSITIVE.search(value))
    if value.endswith("?"):
        return None

    transfer = bool(TRANSFER.search(value))
    # A possible offer or a visa transfer has limits, so it is conditional.
    if re.search(r"\bsponsorship\b.{0,30}\bnot guaranteed\b|\bcannot guarantee\b.{0,30}\bsponsorship\b", value, re.I):
        return "conditional"
    transfer_refused = re.search(r"\b(?:do not|cannot|can't|will not|won't)\s+(?:support|accept|offer|process)\s+(?:visa\s+|h[- ]?1b\s+)?transfers?\b|\bno\s+(?:visa\s+|h[- ]?1b\s+)?transfers?\b", value, re.I)
    if transfer and transfer_refused:
        return "not_available"
    if transfer and re.search(r"\b(?:support|accept|offer|available|only)\b", value, re.I):
        if negative and not re.search(r"\b(?:new|except)\b", value, re.I):
            return "not_available"
        return "conditional"
    if negative:
        if re.search(r"\bunless\b", value, re.I):
            return "conditional"
        return "not_available"
    if positive:
        return "conditional" if CONDITIONAL.search(value) else "mentioned"
    if INTEREST.search(value) and re.search(r"\bsponsor\w*\b", value, re.I) and re.search(r"\b(?:may|might|case.by.case|subject to|consider|considered)\b", value, re.I):
        return "conditional"
    return None


def classify(description):
    """Combine sentence-level rules into one assessment for the whole description.

    Return a category, original quotes, and whether someone should review it.
    An empty description stays not_specified instead of becoming a refusal.
    """
    evidence = []
    ambiguous = False
    for sentence in sentences(description):
        if not INTEREST.search(sentence):
            continue
        status = sentence_status(sentence)
        if status and len(sentence) <= 5000:
            evidence.append({"quote": sentence, "status": status, "method": "rules"})
        elif not NOT_NEEDED.search(normalize(sentence)) and not HISTORICAL.search(sentence):
            ambiguous = True
    categories = {entry["status"] for entry in evidence}
    # Do not choose the attractive offer when another sentence contradicts it.
    conflict = "not_available" in categories and bool(categories & {"mentioned", "conditional"})
    if conflict:
        status = "not_specified"
    elif "not_available" in categories:
        status = "not_available"
    elif "conditional" in categories:
        status = "conditional"
    elif "mentioned" in categories:
        status = "mentioned"
    else:
        status = "not_specified"
    review = conflict or (ambiguous and not categories)
    return {"status": status, "evidence": evidence, "needs_review": review, "method": "rules",
            "notes": "Conflicting statements require review." if conflict else "Sponsorship wording requires review." if review else "Based only on explicit listing statements." if evidence else "No explicit sponsorship offer or refusal found."}


def validate_ai(description, proposal):
    """Check an AI answer against the source text before allowing it to be saved.

    Reject invented or shortened quotes. Keep clear rule-based evidence even
    if AI disagrees. A real quote still needs to support the proposed category.
    """
    baseline = classify(description)
    if baseline["evidence"]:
        return baseline
    if not isinstance(proposal, dict) or proposal.get("status") not in STATUSES:
        raise ValueError("Invalid sponsorship classification.")
    quotes = proposal.get("quotes")
    if not isinstance(quotes, list) or len(quotes) > 8:
        raise ValueError("Expected at most eight supporting quotes.")
    originals = {normalize(sentence): sentence for sentence in sentences(description)}
    # Match whole sentences so a quote cannot leave out "not" or a restriction.
    validated = []
    for quote in quotes:
        if not isinstance(quote, str) or len(quote) > 5000 or normalize(quote) not in originals:
            raise ValueError("Sponsorship evidence must match a complete sentence in the description.")
        original = originals[normalize(quote)]
        if not INTEREST.search(original):
            raise ValueError("Evidence does not discuss sponsorship or immigration.")
        validated.append({"quote": original, "status": proposal["status"], "method": "ai"})
    if proposal["status"] != "not_specified" and not validated:
        raise ValueError("A sponsorship claim needs supporting evidence.")
    grounded = classify("\n".join(entry["quote"] for entry in validated))
    # Finding the words in the listing is not enough to prove an offer exists.
    if proposal["status"] != "not_specified" and grounded["status"] != proposal["status"]:
        return {**baseline, "evidence": [{**entry, "status": "not_specified"} for entry in validated],
                "method": "rules+ai", "needs_review": True, "notes": "AI interpretation could not be independently validated; review the quoted wording."}
    return {**grounded, "evidence": validated, "method": "rules+ai",
            "needs_review": grounded["needs_review"] or baseline["needs_review"], "notes": "AI evidence checked against the original description."}


def description_hash(description):
    """Make a fingerprint of the text and rule version to detect outdated results."""
    return hashlib.sha256((CLASSIFIER_VERSION + "\0" + (description or "")).encode()).hexdigest()


def assessment_values(description, result):
    """Turn an assessment into database fields, adding its date and fingerprint."""
    return {"sponsorship_status": result["status"], "sponsorship_evidence": result["evidence"],
            "sponsorship_needs_review": result["needs_review"], "sponsorship_method": result["method"],
            "sponsorship_notes": result["notes"], "sponsorship_checked_at": datetime.utcnow(),
            "sponsorship_description_hash": description_hash(description)}


def save_assessment(job, result):
    """Copy assessment fields onto a job; the caller saves the database transaction."""
    for field, value in assessment_values(job.description, result).items():
        setattr(job, field, value)


def update_sponsorship(job):
    """Run the rules only when the description or classifier version has changed.

    Reuse an existing AI assessment when its source text and version still match.
    """
    if job.sponsorship_description_hash != description_hash(job.description):
        save_assessment(job, classify(job.description))
