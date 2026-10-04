"""Deterministic scope-rule lexicons and patterns (R2.4-R2.10, R2.13, D12).

The scope guard's first stage matches a message against these Spanish/English
patterns with zero model calls. ``match_category`` folds the message (casefold +
diacritic strip) and returns the highest-precedence category that matches, or
``None`` when no deterministic rule fires (the message then goes to the single
model-assisted call).

Precedence when a message matches several categories (R2.17): UNSAFE wins over
OUT_OF_SCOPE, which wins over IN_SCOPE. UNSAFE reflects R2.8-R2.10 and R2.13;
OUT_OF_SCOPE reflects R2.4-R2.7.

This module imports no provider client and no database driver (import boundary
B1): it is pure pattern matching.
"""

import re
import unicodedata
from typing import Literal

__all__ = ["ScopeCategory", "fold", "match_category"]

ScopeCategory = Literal["UNSAFE", "OUT_OF_SCOPE"]


def fold(text: str) -> str:
    """Casefold and strip diacritics so es/en patterns match accent-insensitively."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _compile(*fragments: str) -> re.Pattern[str]:
    """Compile an alternation of folded, word-bounded fragments."""
    alternation = "|".join(fragments)
    return re.compile(rf"(?:{alternation})")


# ── UNSAFE patterns (R2.8-R2.10, R2.13) ──────────────────────────────────────

# R2.8 — credentials, tokens, code execution, API keys, connection strings,
# hidden/system prompts, internal instructions.
_UNSAFE_SECRETS = _compile(
    r"\bcredential(s)?\b", r"\bcredencial(es)?\b",
    r"\bpassword(s)?\b", r"\bcontrasena(s)?\b", r"\bclave(s)?\b",
    r"\baccess token(s)?\b", r"\btoken(s)? de acceso\b", r"\bapi key(s)?\b",
    r"\bllave(s)? api\b", r"\bsecret(s)?\b", r"\bsecreto(s)?\b",
    r"\bconnection string(s)?\b", r"\bcadena(s)? de conexion\b",
    r"\bsystem prompt\b", r"\bhidden prompt\b", r"\bprompt del sistema\b",
    r"\binternal instruction(s)?\b", r"\binstruccion(es)? interna(s)?\b",
    r"\bejecut(a|ar|e) codigo\b", r"\bexecute code\b", r"\brun code\b",
    r"\benvironment variable(s)?\b", r"\bvariable(s)? de entorno\b",
)

# R2.9 — requests to alter, delete, insert, update or modify data.
_UNSAFE_MODIFY = _compile(
    r"\bdelete\b", r"\bdrop\b", r"\btruncate\b", r"\binsert\b", r"\bupdate\b",
    r"\balter\b", r"\bmodif(y|ies|ical?r?)\b", r"\bborra(r|)\b", r"\belimina(r|)\b",
    r"\bactualiza(r|)\b", r"\binserta(r|)\b", r"\bmodificar\b",
    r"\bwrite to\b", r"\bescribir en\b",
)

# R2.10 — supplying a SQL statement/fragment or requesting DB statement execution.
_UNSAFE_SQL = _compile(
    r"\bselect\b.+\bfrom\b", r"\bsql\b", r"\bexecute (this |the )?(query|statement)\b",
    r"\bejecut(a|ar) (esta |la )?(consulta|sentencia|query)\b",
    r"\bcreate table\b", r"\bunion select\b", r"--", r";--",
)

# R2.13 — prompt-injection: disregard/override/replace/disclose configured role.
_UNSAFE_INJECTION = _compile(
    r"\bignore\b(?:\s+\w+){0,4}\s+(instructions|rules|prompt)\b",
    r"\bdisregard\b(?:\s+\w+){0,4}\s+(instructions|rules|prompt)\b",
    r"\boverride\b(?:\s+\w+){0,4}\s+(instructions|rules|constraints)\b",
    r"\breveal\b(?:\s+\w+){0,4}\s+(system prompt|instructions|rules)\b",
    r"\bdisclose\b(?:\s+\w+){0,4}\s+(system prompt|instructions|rules)\b",
    r"\bignora\b(?:\s+\w+){0,4}\s+(instrucciones|reglas)\b",
    r"\bolvida\b(?:\s+\w+){0,4}\s+(instrucciones|reglas)\b",
    r"\bactua como\b", r"\bact as (if )?\b", r"\byou are now\b",
    r"\bahora eres\b", r"\bpret(e|end)\b",
)

_UNSAFE_PATTERNS = (
    _UNSAFE_SECRETS,
    _UNSAFE_MODIFY,
    _UNSAFE_SQL,
    _UNSAFE_INJECTION,
)

# ── OUT_OF_SCOPE patterns (R2.4-R2.7) ─────────────────────────────────────────

# R2.4 — sales, revenue, finance, marketing, purchasing, inventory, other non-HSE.
_OOS_OPERATIONS = _compile(
    r"\bsales\b", r"\bventa(s)?\b", r"\brevenue\b", r"\bingreso(s)?\b",
    r"\bfinance\b", r"\bfinanc(e|iero|iera|ia)\b", r"\bmarketing\b",
    r"\bmercadeo\b", r"\bpurchasing\b", r"\bcompra(s)?\b", r"\bprocurement\b",
    r"\binventory\b", r"\binventario\b", r"\bprofit\b", r"\bganancia(s)?\b",
    r"\bbudget\b", r"\bpresupuesto\b",
)

# R2.5 — general human-resources unrelated to HSE incident analysis.
_OOS_HR = _compile(
    r"\bpayroll\b", r"\bnomina\b", r"\bsalary\b", r"\bsalario(s)?\b",
    r"\bvacation(s)?\b", r"\bvacacion(es)?\b", r"\bhiring\b", r"\bcontratacion\b",
    r"\brecruit(ing|ment)?\b", r"\bhuman resources\b", r"\brecursos humanos\b",
    r"\bbenefit(s)?\b", r"\bprestacion(es)?\b",
)

# R2.6 — medical diagnosis or treatment advice.
_OOS_MEDICAL = _compile(
    r"\bdiagnos(e|is|tico|ticar)\b", r"\btreatment\b", r"\btratamiento\b",
    r"\bprescrib(e|ir|ption)\b", r"\breceta(r|)\b", r"\bmedication\b",
    r"\bmedicamento(s)?\b", r"\bcure\b", r"\bcura(r|)\b",
    r"\bmedical advice\b", r"\bconsejo medico\b",
)

# R2.7 — legal conclusion, liability assessment, employment decision.
_OOS_LEGAL = _compile(
    r"\blegal(ly)? (liable|responsible|conclusion|advice)\b",
    r"\bliability\b", r"\bresponsabilidad legal\b", r"\bculpa(ble)?\b",
    r"\blawsuit\b", r"\bdemanda(r|)\b", r"\bsue\b", r"\bfire (this |the )?employee\b",
    r"\bdespedir\b", r"\bemployment decision\b", r"\bdecision de empleo\b",
    r"\basesoria legal\b", r"\bconclusion legal\b",
)

_OUT_OF_SCOPE_PATTERNS = (
    _OOS_OPERATIONS,
    _OOS_HR,
    _OOS_MEDICAL,
    _OOS_LEGAL,
)


def match_category(message: str) -> ScopeCategory | None:
    """Return the highest-precedence deterministic category, or None (R2.17).

    UNSAFE takes precedence over OUT_OF_SCOPE. A message matching no pattern
    returns ``None`` and is deferred to the single model-assisted call.
    """
    folded = fold(message)
    if any(pattern.search(folded) for pattern in _UNSAFE_PATTERNS):
        return "UNSAFE"
    if any(pattern.search(folded) for pattern in _OUT_OF_SCOPE_PATTERNS):
        return "OUT_OF_SCOPE"
    return None
