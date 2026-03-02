"""Three-level demand deduplication: exact match, fuzzy match, and semantic match.

Deduplication pipeline:
1. Exact title match (database lookup)
2. Fuzzy match via Levenshtein ratio
3. AI-based semantic match (Claude API) for inconclusive cases

When the demand count exceeds 500, TF-IDF pre-filtering narrows down
candidates before pairwise comparison.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import Levenshtein
from sqlalchemy import func, select

from src.analyzer.prompts import CLASSIFY_DEMAND_PROMPT, format_prompt
from src.storage.database import get_session
from src.storage.models import Demand, DemandRelation
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# TF-IDF threshold for candidate pre-filtering
_TFIDF_CANDIDATE_LIMIT = 20


class DemandDeduplicator:
    """Three-level deduplication engine for workplace demands."""

    def __init__(self) -> None:
        """Load AI configuration for semantic matching."""
        settings = get_settings()
        ai_config = settings.get("ai", {})
        self.model = ai_config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = ai_config.get("max_tokens", 4096)
        self.temperature = ai_config.get("temperature", 0.3)
        self.api_key = ai_config.get("api_key", "")

    # ------------------------------------------------------------------
    # Level 1 — Exact Match
    # ------------------------------------------------------------------

    def find_exact_match(self, title: str) -> Optional[Demand]:
        """Query the database for an exact title match.

        Args:
            title: The demand title to search for.

        Returns:
            The matching ``Demand`` or *None*.
        """
        with get_session() as session:
            stmt = select(Demand).where(Demand.title == title)
            return session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Level 2 — Fuzzy Match
    # ------------------------------------------------------------------

    def find_fuzzy_match(
        self, title: str, threshold: float = 0.8
    ) -> Optional[Tuple[Demand, float]]:
        """Compare the title against all existing demands using Levenshtein ratio.

        Args:
            title: The demand title to compare.
            threshold: Minimum similarity ratio to consider a match.

        Returns:
            A tuple of (best matching ``Demand``, similarity ratio) if the
            ratio exceeds *threshold*, otherwise *None*.
        """
        with get_session() as session:
            demands = self._get_candidate_demands(session, title)

            best_match: Optional[Demand] = None
            best_ratio: float = 0.0

            for demand in demands:
                ratio = Levenshtein.ratio(title, demand.title)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = demand

            if best_match is not None and best_ratio >= threshold:
                # Expunge so the object survives session close
                session.expunge(best_match)
                return best_match, best_ratio

        return None

    # ------------------------------------------------------------------
    # Level 3 — Semantic Match (AI)
    # ------------------------------------------------------------------

    def find_semantic_match(
        self, title: str, description: str
    ) -> Optional[Tuple[Demand, float]]:
        """Use the Claude API to find semantically similar demands.

        Only intended to be called when fuzzy matching is inconclusive
        (i.e. best fuzzy ratio falls between 0.5 and 0.8).

        Args:
            title: The demand title.
            description: The demand description.

        Returns:
            A tuple of (matching ``Demand``, similarity score) if a
            semantic match is found, otherwise *None*.
        """
        import anthropic

        with get_session() as session:
            candidates = self._get_candidate_demands(session, title)
            if not candidates:
                return None

            candidate_texts = [
                {"id": d.id, "title": d.title, "description": d.description or ""}
                for d in candidates
            ]

            prompt = format_prompt(
                CLASSIFY_DEMAND_PROMPT,
                new_title=title,
                new_description=description,
                candidates=json.dumps(candidate_texts, ensure_ascii=False),
            )

            try:
                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                result_text = response.content[0].text
                result = json.loads(result_text)
                matched_id = result.get("matched_id")
                similarity = float(result.get("similarity", 0))

                if matched_id and similarity > 0.5:
                    matched = session.get(Demand, matched_id)
                    if matched:
                        session.expunge(matched)
                        return matched, similarity

            except Exception:
                logger.warning("Semantic match failed for '{}', skipping", title)

        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def deduplicate(self, demand_data: Dict) -> Tuple[bool, Optional[int]]:
        """Run the demand through all three deduplication levels.

        Args:
            demand_data: Dictionary with at least ``title`` and optionally
                ``description`` and ``tags``.

        Returns:
            A tuple ``(is_duplicate, existing_demand_id)``.
            If no match is found, returns ``(False, None)``.
        """
        title = demand_data.get("title", "")
        description = demand_data.get("description", "")

        # Level 1: exact match
        exact = self.find_exact_match(title)
        if exact:
            self.merge_demands(exact, demand_data, similarity=1.0)
            logger.info("Exact duplicate found for '{}'", title)
            return True, exact.id

        # Level 2: fuzzy match
        fuzzy_result = self.find_fuzzy_match(title)
        if fuzzy_result:
            demand, ratio = fuzzy_result
            self.merge_demands(demand, demand_data, similarity=ratio)
            logger.info("Fuzzy duplicate (ratio={:.2f}) for '{}'", ratio, title)
            return True, demand.id

        # Check if fuzzy is inconclusive (best ratio between 0.5 and 0.8)
        inconclusive = self.find_fuzzy_match(title, threshold=0.5)
        if inconclusive:
            _, fuzzy_ratio = inconclusive

            # Level 3: semantic match
            if 0.5 < fuzzy_ratio < 0.8:
                semantic_result = self.find_semantic_match(title, description)
                if semantic_result:
                    demand, sim_score = semantic_result
                    self.merge_demands(demand, demand_data, similarity=sim_score)
                    self._save_relation(demand.id, demand_data, sim_score)
                    logger.info(
                        "Semantic duplicate (score={:.2f}) for '{}'",
                        sim_score,
                        title,
                    )
                    return True, demand.id

                # Even without a full match, save relation if similarity > 0.5
                if semantic_result is None and inconclusive:
                    fuzzy_demand, _ = inconclusive
                    self._save_relation(fuzzy_demand.id, demand_data, fuzzy_ratio)

        return False, None

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    def merge_demands(
        self, existing: Demand, new_data: Dict, similarity: float
    ) -> None:
        """Merge a new demand into an existing one.

        - Increments frequency.
        - Updates ``last_seen``.
        - Keeps the longer/better description.
        - Merges tags (set union).

        Args:
            existing: The existing ``Demand`` ORM object.
            new_data: Dictionary with new demand fields.
            similarity: The similarity score that triggered the merge.
        """
        with get_session() as session:
            demand = session.get(Demand, existing.id)
            if demand is None:
                return

            demand.frequency = (demand.frequency or 1) + 1
            demand.last_seen = datetime.now()

            new_desc = new_data.get("description", "") or ""
            if len(new_desc) > len(demand.description or ""):
                demand.description = new_desc

            # Merge tags (union)
            existing_tags = set(json.loads(demand.tags)) if demand.tags else set()
            new_tags_raw = new_data.get("tags", "")
            if isinstance(new_tags_raw, str) and new_tags_raw:
                try:
                    new_tags = set(json.loads(new_tags_raw))
                except (json.JSONDecodeError, TypeError):
                    new_tags = set()
            elif isinstance(new_tags_raw, list):
                new_tags = set(new_tags_raw)
            else:
                new_tags = set()

            merged_tags = sorted(existing_tags | new_tags)
            demand.tags = json.dumps(merged_tags, ensure_ascii=False)

            logger.debug(
                "Merged demand id={} (similarity={:.2f}, freq={})",
                demand.id,
                similarity,
                demand.frequency,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_relation(
        self, existing_id: int, new_data: Dict, similarity: float
    ) -> None:
        """Save a demand relation when semantic similarity exceeds 0.5.

        Args:
            existing_id: ID of the existing demand.
            new_data: Dictionary with new demand data (must have been saved
                to obtain an ``id``).
            similarity: Similarity score between the two demands.
        """
        new_id = new_data.get("id")
        if new_id is None or similarity <= 0.5:
            return

        with get_session() as session:
            # Ensure consistent ordering to avoid duplicate pairs
            id_a, id_b = sorted([existing_id, new_id])
            exists = session.execute(
                select(DemandRelation).where(
                    DemandRelation.demand_id_a == id_a,
                    DemandRelation.demand_id_b == id_b,
                )
            ).scalar_one_or_none()
            if exists is None:
                relation = DemandRelation(
                    demand_id_a=id_a,
                    demand_id_b=id_b,
                    similarity_score=similarity,
                )
                session.add(relation)
                logger.debug("Saved demand relation ({}, {}, {:.2f})", id_a, id_b, similarity)

    def _get_candidate_demands(
        self, session, title: str  # noqa: ANN001 – Session type
    ) -> List[Demand]:
        """Return candidate demands for comparison.

        When the total demand count exceeds 500, TF-IDF pre-filtering is
        used to narrow candidates before pairwise comparison.

        Args:
            session: An active SQLAlchemy session.
            title: The title to find candidates for.

        Returns:
            A list of ``Demand`` objects to compare against.
        """
        total = session.execute(select(func.count(Demand.id))).scalar() or 0

        if total <= 500:
            return list(session.execute(select(Demand)).scalars().all())

        # TF-IDF pre-filtering for large datasets
        return self._tfidf_filter(session, title)

    def _tfidf_filter(
        self, session, title: str  # noqa: ANN001
    ) -> List[Demand]:
        """Use TF-IDF with jieba tokenisation to find the most similar demands.

        Args:
            session: An active SQLAlchemy session.
            title: The new demand title.

        Returns:
            Top candidates ranked by TF-IDF cosine similarity.
        """
        import jieba
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        demands = list(session.execute(select(Demand)).scalars().all())
        if not demands:
            return []

        corpus = [" ".join(jieba.cut(d.title)) for d in demands]
        query = " ".join(jieba.cut(title))

        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(corpus + [query])

        query_vec = tfidf_matrix[-1]
        similarities = cosine_similarity(query_vec, tfidf_matrix[:-1]).flatten()

        top_indices = similarities.argsort()[::-1][:_TFIDF_CANDIDATE_LIMIT]
        return [demands[i] for i in top_indices]
