from __future__ import annotations
import hashlib
import math
import re
from dataclasses import dataclass
from .models import Incident


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*|[\u4e00-\u9fff]")


def tokens(text: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(text)]


def embed(text: str, dims: int = 96) -> list[float]:
    """Offline deterministic hashing embedding; replace with a model in production."""
    vector = [0.0] * dims
    items = tokens(text)
    for size in (1, 2, 3):
        for i in range(max(0, len(items) - size + 1)):
            gram = "".join(items[i : i + size]).encode()
            digest = hashlib.sha256(gram).digest()
            index = int.from_bytes(digest[:4], "big") % dims
            vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def incident_text(row: Incident, service_names: list[str] | None = None) -> str:
    return " ".join([row.title, row.symptom, row.root_cause, row.resolution, " ".join(row.error_codes or []), " ".join(service_names or [])])


def lexical_score(query: str, document: str) -> float:
    q = tokens(query)
    d = tokens(document)
    if not q or not d:
        return 0.0
    counts = {term: d.count(term) for term in set(q)}
    exact = sum(counts.values()) / len(q)
    phrase = 2.0 if query.lower() in document.lower() else 0.0
    identifiers = sum(3.0 for term in q if ("_" in term or "-" in term or any(c.isdigit() for c in term)) and term in d)
    return exact + phrase + identifiers


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def exact_identifier_match(query: str, row: Incident, service_names: list[str]) -> bool:
    """Do not let semantic rank dilute a unique error code or service identifier."""
    query_tokens = set(tokens(query))
    identifiers = {item.lower() for item in (row.error_codes or []) + service_names}
    return bool(query_tokens.intersection(identifiers))


def trusted_match(scores: dict, mode: str) -> bool:
    """Conservative offline baseline threshold; tune on production embeddings."""
    if mode == "fts":
        return scores["fts_score"] >= 0.6
    if mode == "vector":
        return scores["vector_score"] >= 0.3
    return scores["fts_score"] >= 0.6 or scores["vector_score"] >= 0.3


def rank(rows: list[tuple[Incident, list[str]]], query: str, mode: str, k: int = 60) -> list[tuple[Incident, dict]]:
    lexical = sorted(rows, key=lambda pair: lexical_score(query, incident_text(*pair)), reverse=True)
    qvec = embed(query)
    semantic = sorted(rows, key=lambda pair: cosine(qvec, pair[0].embedding or embed(incident_text(*pair))), reverse=True)
    lr = {row.id: i + 1 for i, (row, _) in enumerate(lexical)}
    vr = {row.id: i + 1 for i, (row, _) in enumerate(semantic)}
    lookup = {row.id: (row, services) for row, services in rows}
    scores: dict[str, dict] = {}
    for incident_id in lookup:
        ls = lexical_score(query, incident_text(*lookup[incident_id]))
        vs = cosine(qvec, lookup[incident_id][0].embedding or embed(incident_text(*lookup[incident_id])))
        exact = exact_identifier_match(query, lookup[incident_id][0], lookup[incident_id][1])
        if mode == "fts":
            combined = ls
        elif mode == "vector":
            combined = vs
        else:
            combined = (1 / (k + lr[incident_id]) if ls > 0 else 0) + 1 / (k + vr[incident_id]) + (1.0 if exact else 0.0)
        scores[incident_id] = {"score": round(combined, 6), "fts_score": round(ls, 6), "vector_score": round(vs, 6), "exact_identifier": exact}
    ordered = sorted(lookup, key=lambda item: scores[item]["score"], reverse=True)
    return [(lookup[item][0], scores[item] | {"services": lookup[item][1]}) for item in ordered]
