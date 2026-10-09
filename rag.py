from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np


EVIDENCE_STATUSES = {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "CONFLICTING"}

# These are question/grammar words, not policy claims. Keeping the claim vocabulary
# separate makes the evidence gate deterministic and auditable.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "could", "do", "does", "for",
    "from", "get", "gets", "has", "have", "how", "i", "if", "in", "is", "it", "me",
    "of", "on", "or", "our", "please", "the", "their", "they", "this", "to", "up",
    "us", "what", "when", "where", "which", "who", "with", "would", "you", "your",
}

_CANONICAL = {
    "members": "member",
    "member": "member",
    "benefits": "benefit",
    "benefit": "benefit",
    "complimentary": "complimentary",
    "free": "complimentary",
    "upgrade": "upgrade",
    "upgrades": "upgrade",
    "availability": "availability",
    "available": "availability",
    "unavailable": "availability",
    "modify": "modify",
    "modified": "modify",
    "modification": "modify",
    "modifications": "modify",
    "change": "modify",
    "changes": "modify",
    "changed": "modify",
    "reservation": "reservation",
    "reservations": "reservation",
    "dates": "date",
    "date": "date",
    "rooms": "room",
    "room": "room",
    "policies": "policy",
    "rules": "rule",
    "fees": "fee",
}

_TIER_TERMS = {"gold", "silver", "platinum", "member"}
_NEGATIVE_MARKERS = ("must not", "does not", "do not", "not allowed", "prohibited", "forbidden", "no ")
_POSITIVE_MARKERS = ("may ", "receive", "allowed", "included", "complimentary", "available", "can ")


def split_policy_sections(text: str) -> list[dict[str, str]]:
    """
    Expected heading format:
      ## POL-RES-01 | Reservation Modification Policy
    """
    pattern = re.compile(r"^##\s+([A-Z0-9-]+)\s*\|\s*(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    chunks: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunks.append({"policy_id": match.group(1), "title": match.group(2).strip(), "text": body})
    return chunks


def _canonical_token(token: str) -> str:
    token = token.lower()
    if token in _CANONICAL:
        return _CANONICAL[token]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _terms(text: str, *, query: bool) -> set[str]:
    raw_tokens = list(re.finditer(r"[A-Za-z0-9]+", text))
    terms: set[str] = set()
    for index, match in enumerate(raw_tokens):
        original = match.group(0)
        lower = original.lower()
        canonical = _canonical_token(lower)
        if lower in _STOPWORDS or canonical in _STOPWORDS:
            continue

        # Ignore likely person/place names in user questions so "Jessica Turner" does
        # not lower the support score for an otherwise well-grounded policy claim.
        if (
            query
            and index > 0
            and original[:1].isupper()
            and canonical not in _TIER_TERMS
            and not original.isupper()
        ):
            continue
        terms.add(canonical)

    # A check-in/check-out reference is a date concept even when the literal word
    # "date" is absent from the policy text.
    if re.search(r"\bcheck[- ]?(?:in|out)\b", text, flags=re.IGNORECASE):
        terms.add("date")
    return terms


def _candidate_polarity(text: str, claim_terms: set[str]) -> str:
    """Coarse conflict detector for two policy sections that address the same claim."""
    if not claim_terms:
        return "neutral"
    positive = 0
    negative = 0
    for sentence in re.split(r"(?<=[.!?])\s+", text.lower()):
        sentence_terms = _terms(sentence, query=False)
        overlap = len(claim_terms & sentence_terms) / max(1, len(claim_terms))
        if overlap < 0.5:
            continue
        if any(marker in sentence for marker in _NEGATIVE_MARKERS):
            # Negation wins within the sentence: "must not receive complimentary..."
            # is negative evidence, not both positive and negative.
            negative += 1
        elif any(marker in sentence for marker in _POSITIVE_MARKERS):
            positive += 1
    if positive and not negative:
        return "positive"
    if negative and not positive:
        return "negative"
    return "neutral"


class PolicyRAG:
    """
    Lightweight RAG with a separate grounding gate:
    - Retrieval finds plausible policy candidates.
    - Evidence classification decides whether a policy answer may be shown.
    - Production: OpenAI embeddings + local JSON cache.
    - Offline/test: deterministic local hashed bag-of-words vectors.
    """

    def __init__(
        self,
        policy_path: str | Path,
        cache_path: str | Path,
        *,
        embedding_model: str,
        api_key: str | None = None,
        offline: bool = False,
        threshold: float = 0.08,
        min_relevance_score: float,
    ):
        self.policy_path = Path(policy_path)
        self.cache_path = Path(cache_path)
        self.embedding_model = embedding_model
        self.api_key = api_key
        self.offline = offline or not bool(api_key)
        self.threshold = threshold
        self.min_relevance_score = min_relevance_score
        self.sections = split_policy_sections(self.policy_path.read_text(encoding="utf-8"))
        if not self.sections:
            raise ValueError("No policy sections found. Expected headings like '## POL-ID | Title'.")

    @property
    def ready(self) -> bool:
        return bool(self.sections)

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        self.cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    def _local_embedding(self, text: str, size: int = 256) -> list[float]:
        """
        Offline/test-only fallback. Production uses OpenAI embeddings.
        This keeps automated tests usable without an API key.
        """
        vec = np.zeros(size, dtype=float)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % size
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm:
            vec /= norm
        return vec.tolist()

    def _openai_embeddings(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.embeddings.create(model=self.embedding_model, input=texts)
        return [item.embedding for item in response.data]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.offline:
            return [self._local_embedding(t) for t in texts]
        return self._openai_embeddings(texts)

    def _chunk_embeddings(self) -> list[list[float]]:
        mode = "offline-local" if self.offline else self.embedding_model
        cache = self._load_cache()
        cache.setdefault("version", 1)
        cache.setdefault("vectors", {})

        vectors: list[list[float] | None] = []
        missing_texts: list[str] = []
        missing_keys: list[str] = []

        for section in self.sections:
            text = f"{section['policy_id']} {section['title']}\n{section['text']}"
            key = f"{mode}:{self._hash(text)}"
            if key in cache["vectors"]:
                vectors.append(cache["vectors"][key])
            else:
                vectors.append(None)
                missing_texts.append(text)
                missing_keys.append(key)

        if missing_texts:
            new_vectors = self.embed(missing_texts)
            for key, vector in zip(missing_keys, new_vectors):
                cache["vectors"][key] = vector
            self._save_cache(cache)

            new_iter = iter(new_vectors)
            vectors = [next(new_iter) if v is None else v for v in vectors]

        return [v for v in vectors if v is not None]

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        va = np.asarray(a, dtype=float)
        vb = np.asarray(b, dtype=float)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(np.dot(va, vb) / denom) if denom else 0.0

    def _claim_coverage(self, query: str, section: dict[str, str]) -> float:
        claim_terms = _terms(query, query=True)
        if not claim_terms:
            return 0.0
        policy_terms = _terms(f"{section['title']} {section['text']}", query=False)
        return len(claim_terms & policy_terms) / len(claim_terms)

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Retrieve candidates, then calculate a calibrated relevance score.

        `embedding_similarity_score` is the raw cosine score. `similarity_score`
        combines semantic similarity with direct claim-term coverage so the safety
        threshold is meaningful in both online and deterministic offline modes.
        """
        chunk_vectors = self._chunk_embeddings()
        query_vector = self.embed([query])[0]
        scored: list[dict[str, Any]] = []
        for section, vector in zip(self.sections, chunk_vectors):
            raw_similarity = self.cosine(query_vector, vector)
            if raw_similarity < self.threshold:
                continue
            coverage = self._claim_coverage(query, section)
            semantic_norm = min(1.0, max(0.0, raw_similarity) / 0.5)
            relevance = (0.85 * coverage) + (0.15 * semantic_norm)
            scored.append(
                {
                    **section,
                    "similarity_score": round(relevance, 4),
                    "embedding_similarity_score": round(raw_similarity, 4),
                    "claim_coverage": round(coverage, 4),
                }
            )
        scored.sort(key=lambda x: (x["similarity_score"], x["embedding_similarity_score"]), reverse=True)
        return scored[:top_k]

    def evaluate_evidence(self, query: str, top_k: int = 3) -> dict[str, Any]:
        """
        Backend-enforced evidence classification. Only SUPPORTED permits a confident
        policy answer. PARTIALLY_SUPPORTED, NOT_SUPPORTED, and CONFLICTING escalate.
        """
        matches = self.retrieve(query, top_k=top_k)
        base = {
            "query": query,
            "matches": matches,
            "min_relevance_score": self.min_relevance_score,
            "answer_allowed": False,
            "requires_escalation": True,
        }
        if not matches:
            return {
                **base,
                "evidence_status": "NOT_SUPPORTED",
                "evidence_reason": "No relevant policy section was retrieved.",
            }

        top = matches[0]
        top_score = float(top["similarity_score"])
        coverage = float(top["claim_coverage"])
        if top_score < self.min_relevance_score:
            return {
                **base,
                "evidence_status": "NOT_SUPPORTED",
                "evidence_reason": "The best policy evidence is below the configured relevance threshold.",
            }

        # Conflicting evidence: two strong sections cover the claim but have opposite polarity.
        claim_terms = _terms(query, query=True)
        strong = [
            item
            for item in matches
            if float(item["similarity_score"]) >= self.min_relevance_score
            and float(item["claim_coverage"]) >= 0.8
        ]
        polarities = {
            _candidate_polarity(item["text"], claim_terms)
            for item in strong
        } - {"neutral"}
        if {"positive", "negative"}.issubset(polarities):
            return {
                **base,
                "evidence_status": "CONFLICTING",
                "evidence_reason": "Retrieved policy sections provide conflicting support for the requested claim.",
            }

        # Ambiguous near-tie across distinct policies is not treated as fully grounded.
        if len(strong) >= 2:
            first, second = strong[0], strong[1]
            if (
                first["policy_id"] != second["policy_id"]
                and abs(float(first["similarity_score"]) - float(second["similarity_score"])) < 0.05
            ):
                return {
                    **base,
                    "evidence_status": "PARTIALLY_SUPPORTED",
                    "evidence_reason": "Multiple policy sections are similarly relevant, so staff review is required.",
                }

        if coverage < 0.8:
            return {
                **base,
                "evidence_status": "PARTIALLY_SUPPORTED",
                "evidence_reason": "The retrieved policy covers only part of the requested claim.",
            }

        return {
            **base,
            "evidence_status": "SUPPORTED",
            "evidence_reason": "The retrieved policy directly supports the requested claim.",
            "answer_allowed": True,
            "requires_escalation": False,
        }
