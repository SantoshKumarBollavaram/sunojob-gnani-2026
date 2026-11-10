"""Deterministic readback of every active field; no free-form AI summary."""


def readback_text(card, language):
    te = language == "te-IN"
    parts = ["మీ సూచనలను వినండి." if te else "Please review these instructions."]
    quoted = set()
    for item in card["extraction"]["instructions"]:
        key = (item["kind"], item["subject"], item["value"])
        known = {
            ("task", "lunch_boxes", "prepare"): "భోజన పెట్టెలు సిద్ధం చేయాలి." if te else "Prepare lunch boxes.",
            ("prohibition", "onion", "exclude"): "ఉల్లిపాయ వేయకూడదు." if te else "Do not add onion.",
            ("permission_required", "menu_change", "ask_first"): "మెనూ మార్చే ముందు నన్ను అడగాలి." if te else "Ask me before changing the menu.",
        }
        if key in known:
            parts.append(known[key])
        elif item["kind"] == "quantity" and item["subject"] == "lunch_boxes":
            parts.append(("భోజన పెట్టెల సంఖ్య: " if te else "Number of lunch boxes: ") + item["value"] + ".")
        else:
            # Unknown subjects retain value AND verbatim evidence rather than
            # inventing a fluent translation or dropping a condition.
            label = ("సూచన" if te else item["kind"].replace("_", " "))
            parts.append(f"{label}: {item['subject'].replace('_', ' ')}: {item['value']}.")
        # Retain supporting wording, including exceptions/conditions that a
        # canonical label alone could flatten. Deduplicate identical quotes.
        for evidence in item["evidence"]:
            if evidence["quote"] not in quoted:
                parts.append(("మీ మాటలు: " if te else "Your words: ") + evidence["quote"])
                quoted.add(evidence["quote"])
    for change in card["extraction"]["corrections"]:
        parts.append((f"ముందు {change['before']}. ఇప్పుడు {change['after']}." if te else
                      f"Correction: earlier {change['before']}; now {change['after']}."))
    for question in card["extraction"]["questions"]:
        parts.append(("వివరణ కావాలి: " if te else "Please clarify: ") + question["text"])
    parts.append("అన్నీ సరైనవైతే అవును అని చెప్పండి. మార్పు ఉంటే వివరించండి." if te else
                 "If everything is correct, say I confirm. Otherwise, tell me what should change.")
    text = " ".join(parts)
    if len(text) > 4000:
        raise ValueError("This card is too long for one spoken readback; split the request")
    return text
