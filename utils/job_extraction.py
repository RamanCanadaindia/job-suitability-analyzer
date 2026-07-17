import re


NOT_MENTIONED = "Not Mentioned"


def _search(pattern, text, flags=re.IGNORECASE):
    match = re.search(pattern, text, flags)
    return match.group(0).strip() if match else None


def _yes_no(text, pattern):
    return "Yes" if re.search(pattern, text, re.IGNORECASE) else "No"


def apply_evidence_rules(description, extracted):
    """Override factual job fields using only evidence in the job listing."""
    text = re.sub(r"[ \t]+", " ", description or "").strip()
    result = dict(extracted or {})

    salary = _search(
        r"\$\s*[\d,]+(?:\.\d{2})?\s*(?:[-\u2013\u2014]|to)\s*"
        r"\$?\s*[\d,]+(?:\.\d{2})?\s*(?:(?:per|an)\s+|/)"
        r"(?:hour|year|month|week|annum)",
        text,
    ) or _search(
        r"\$\s*[\d,]+(?:\.\d{2})?\s*(?:(?:per|an)\s+|/)"
        r"(?:hour|year|month|week|annum)",
        text,
    )
    result["salary"] = salary or NOT_MENTIONED

    employment_types = []
    for pattern, label in (
        (r"\bfull[- ]time\b", "Full-time"),
        (r"\bpart[- ]time\b", "Part-time"),
        (r"\bcontract(?:or)?\b", "Contract"),
        (r"\btemporary\b", "Temporary"),
        (r"\bpermanent\b", "Permanent"),
        (r"\bcasual\b", "Casual"),
    ):
        if re.search(pattern, text, re.IGNORECASE):
            employment_types.append(label)
    result["employment_type"] = ", ".join(employment_types) or NOT_MENTIONED

    if re.search(r"\bremote\b|work from home", text, re.IGNORECASE):
        result["work_mode"] = "Remote"
    elif re.search(r"\bhybrid\b", text, re.IGNORECASE):
        result["work_mode"] = "Hybrid"
    elif re.search(r"\bon[- ]site\b|\bin[- ]office\b", text, re.IGNORECASE):
        result["work_mode"] = "On-site"
    else:
        result["work_mode"] = NOT_MENTIONED

    experience = _search(
        r"\b\d+(?:\s*[-\u2013\u2014]\s*\d+)?\+?\s+years?(?:\s+of)?\s+"
        r"[A-Za-z][^.;\n]{0,70}",
        text,
    )
    result["experience_required"] = experience or NOT_MENTIONED

    education = _search(
        r"\b(?:bachelor(?:'s)?|master(?:'s)?|degree|diploma|certificate)\b[^.;\n]{0,80}",
        text,
    )
    result["education"] = education or NOT_MENTIONED

    cpa = _search(r"\bCPA\b[^.;\n]{0,80}", text)
    result["cpa_requirement"] = cpa or NOT_MENTIONED

    result["financial_statements"] = _yes_no(
        text, r"financial statements?|profit and loss|income statements?|balance sheets?"
    )
    result["year_end"] = _yes_no(text, r"\byear[- ]end\b")
    result["payroll"] = _yes_no(text, r"\bpayroll\b|source deductions?")
    result["client_interaction"] = _yes_no(
        text, r"communicat(?:e|ion|ing) with clients?|client-facing|request missing documents"
    )

    tax_items = []
    for token in ("GST", "HST", "PST", "WCB", "T1", "T2"):
        if re.search(rf"\b{token}\b", text, re.IGNORECASE):
            tax_items.append(token)
    result["gst_pst_wcb"] = ", ".join(
        item for item in tax_items if item in {"GST", "HST", "PST", "WCB"}
    ) or NOT_MENTIONED
    if tax_items and re.search(r"tax|filing|return|prepar", text, re.IGNORECASE):
        result["tax_experience"] = f"{', '.join(tax_items)} preparation/filing"
    else:
        result["tax_experience"] = NOT_MENTIONED

    filing_items = []
    if re.search(r"\bCRA\b", text, re.IGNORECASE):
        filing_items.append("CRA")
    sales_tax = [item for item in tax_items if item in {"GST", "HST", "PST"}]
    if sales_tax and re.search(r"filing|file|returns?", text, re.IGNORECASE):
        filing_items.append(f"{'/'.join(sales_tax)} filing")
    result["government_filing"] = ", ".join(filing_items) or NOT_MENTIONED

    software = []
    for pattern, label in (
        (r"\bQuickBooks Online\b|\bQBO\b", "QuickBooks Online"),
        (r"\bQuickBooks Desktop\b", "QuickBooks Desktop"),
        (r"\bProfile Tax\b", "Profile Tax"),
        (r"\bCaseWare\b", "CaseWare"),
        (r"\bSage(?:\s+\d+)?\b", "Sage"),
        (r"\bXero\b", "Xero"),
        (r"\bMicrosoft Excel\b|\bMS Excel\b|\bExcel\b", "Microsoft Excel"),
    ):
        if re.search(pattern, text, re.IGNORECASE):
            software.append(label)
    result["software"] = ", ".join(software) or NOT_MENTIONED

    return result
