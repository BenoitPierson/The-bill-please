"""Turn user corrections into extraction rules Claude follows next time.

A raw correction ("invoice_number: RCP-4471 -> INV025554") is a *value*, and
values don't generalise: replaying them on the next invoice teaches nothing.
What generalises is the *reason* behind the correction — "on this supplier's
invoices the number to keep is the one labelled CV INVOICE NUMBER, not the
Receipt No. printed above it".

So corrections are logged verbatim (the ground truth, always auditable), and a
separate cheap Claude call distills them into one short rule per supplier. Those
rules are injected into the extraction prompt, where they override the generic
instructions. A rule is refined as more corrections accumulate, never blindly
appended, which keeps the prompt small no matter how long the tool is used.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from anthropic import Anthropic

import db

logger = logging.getLogger("uvicorn.error")

RULE_MODEL = "claude-sonnet-5"
MAX_RULE_CHARS = 400
MAX_RULES_IN_PROMPT = 60

RULE_SYSTEM_PROMPT = """Tu analyses les corrections qu'un comptable a apportees a la main aux \
donnees extraites automatiquement de ses factures. Ton but est d'en deduire UNE consigne \
courte et generalisable, qui evitera de refaire la meme erreur sur les prochaines factures.

Principes :
- Cherche la REGLE derriere les corrections, pas les valeurs corrigees. "Le numero a retenir \
est celui precede de CV INVOICE NUMBER en bas a droite" est utile ; "le numero etait \
INV025554" ne l'est pas.
- Ecris la consigne a l'imperatif, en francais, en une ou deux phrases maximum.
- Si une consigne precedente existe, reformule-la en integrant les nouvelles corrections \
plutot que d'ajouter une seconde consigne.
- Si les corrections sont trop heterogenes ou trop peu nombreuses pour en tirer une regle \
fiable, reponds exactement : AUCUNE REGLE
- Ne parle jamais d'une facture en particulier : la consigne doit valoir pour les suivantes."""


def _format_corrections(corrections: Sequence) -> str:
    lines = []
    for correction in corrections:
        lines.append(
            "- champ {} : extrait \"{}\" -> corrige en \"{}\"".format(
                correction["field"],
                (correction["old_value"] or "(vide)")[:120],
                (correction["new_value"] or "(vide)")[:120],
            )
        )
    return "\n".join(lines)


def _ask_for_rule(
    client: Anthropic,
    supplier_name: Optional[str],
    corrections: Sequence,
    existing_rule: Optional[str],
) -> Optional[str]:
    scope = (
        "les factures du fournisseur \"{}\"".format(supplier_name)
        if supplier_name
        else "toutes les factures, quel que soit le fournisseur"
    )
    prompt = "Corrections observees sur {} :\n{}".format(scope, _format_corrections(corrections))
    if existing_rule:
        prompt += "\n\nConsigne actuellement appliquee (a reformuler si besoin) :\n{}".format(
            existing_rule
        )
    prompt += "\n\nDonne la consigne a appliquer aux prochaines factures."

    response = client.messages.create(
        model=RULE_MODEL,
        max_tokens=400,
        thinking={"type": "disabled"},
        system=RULE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        return None

    rule = " ".join(text_block.text.split()).strip()
    if not rule or rule.upper().startswith("AUCUNE REGLE"):
        return None

    # The model sometimes prefixes the sentence with a label; it adds nothing
    # once the rule is displayed in its own list.
    for prefix in ("Consigne :", "Consigne:", "Règle :", "Regle :", "Règle:", "Regle:"):
        if rule.startswith(prefix):
            rule = rule[len(prefix):].strip()
            break
    return rule[:MAX_RULE_CHARS]


def refresh_rules(client: Anthropic, slug: str) -> Dict[str, int]:
    """Distill every pending correction into per-supplier rules.

    Returns a small summary so the UI can tell the user what happened.
    """
    pending = db.pending_corrections(slug)
    if not pending:
        return {"corrections": 0, "rules_updated": 0}

    by_supplier: Dict[str, List] = {}
    for correction in pending:
        by_supplier.setdefault(correction["supplier_name"] or "", []).append(correction)

    existing = {(r["supplier_name"] or ""): r["rule"] for r in db.list_rules(slug)}

    rules_updated = 0
    learned_ids: List[int] = []

    for supplier, corrections in by_supplier.items():
        try:
            rule = _ask_for_rule(client, supplier or None, corrections, existing.get(supplier))
        except Exception as exc:  # noqa: BLE001 - learning must never break the app
            logger.warning("Apprentissage impossible pour %r : %s", supplier or "(global)", exc)
            continue

        # Consumed either way: corrections too vague to yield a rule should not
        # be re-analysed on every run.
        learned_ids.extend(c["id"] for c in corrections)
        if rule:
            db.upsert_rule(slug, supplier or None, rule, len(corrections))
            rules_updated += 1

    db.mark_corrections_learned(slug, learned_ids)
    logger.info(
        "[%s] %d correction(s) analysee(s), %d regle(s) mise(s) a jour",
        slug,
        len(learned_ids),
        rules_updated,
    )
    return {"corrections": len(learned_ids), "rules_updated": rules_updated}


def rules_for_prompt(slug: str) -> List[str]:
    """The learned rules, formatted for injection into the extraction prompt.

    All of a tenant's rules are sent on every extraction: the supplier is only
    known *after* extraction, so there is no way to select the right rule
    beforehand. They are one or two sentences each and sit in the cached prompt
    prefix, so the cost stays negligible.
    """
    formatted = []
    for row in db.list_rules(slug)[:MAX_RULES_IN_PROMPT]:
        supplier = row["supplier_name"]
        scope = "Fournisseur {}".format(supplier) if supplier else "Toutes factures"
        formatted.append("[{}] {}".format(scope, row["rule"]))
    return formatted
