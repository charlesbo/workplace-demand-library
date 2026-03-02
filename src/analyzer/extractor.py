"""Core AI demand extractor for the workplace demand library.

Uses LLM providers (Anthropic / OpenAI / Ollama) to extract structured
workplace demands from articles and comments, persist them to the database,
and flag high-importance findings.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

import anthropic
import requests

from src.analyzer.prompts import (
    COMMENT_ANALYSIS_PROMPT,
    EXTRACT_DEMANDS_PROMPT,
    VALID_CATEGORIES,
    format_prompt,
)
from src.storage.database import get_session, get_unanalyzed_articles, save_demand
from src.storage.models import Article, ArticleDemandRelation, Demand, HotComment
from src.utils.config import get_settings
from src.utils.logger import get_logger, highlight_important

logger = get_logger(__name__)


class DemandExtractor:
    """Extract workplace demands from articles and comments via LLM calls.

    Attributes:
        provider: AI provider name (``"anthropic"``, ``"openai"``, or ``"ollama"``).
        api_key: API key for the chosen provider.
        model: Model identifier (e.g. ``"claude-sonnet-4-20250514"``).
        max_tokens: Maximum tokens per LLM response.
        temperature: Sampling temperature.
        batch_size: Default number of articles per batch run.
        daily_budget: Maximum API calls allowed per day.
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        """Load AI configuration from settings and initialise counters."""
        settings = get_settings()
        ai_cfg: Dict[str, Any] = settings.get("ai", {})

        self.provider: str = ai_cfg.get("provider", "anthropic")
        self.api_key: str = ai_cfg.get("api_key", "")
        self.model: str = ai_cfg.get("model", "claude-sonnet-4-20250514")
        self.max_tokens: int = int(ai_cfg.get("max_tokens", 4096))
        self.temperature: float = float(ai_cfg.get("temperature", 0.3))
        self.batch_size: int = int(ai_cfg.get("batch_size", 5))
        self.daily_budget: int = int(ai_cfg.get("daily_budget", 100))

        self._call_count: int = 0
        self._total_tokens: int = 0

        logger.info(
            "DemandExtractor initialised — provider={}, model={}, budget={}",
            self.provider,
            self.model,
            self.daily_budget,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_article(self, article: Article) -> List[Dict]:
        """Extract workplace demands from a single article.

        Args:
            article: An :class:`Article` ORM instance with at least
                ``title``, ``platform``, ``content``, and ``language`` populated.

        Returns:
            A list of demand dicts, each containing keys such as *title*,
            *description*, *category*, *subcategory*, *tags*, and
            *importance_score*.

        Raises:
            ValueError: If the LLM response cannot be parsed as valid JSON
                or lacks the expected ``demands`` key.
        """
        prompt = format_prompt(
            EXTRACT_DEMANDS_PROMPT,
            title=article.title,
            platform=article.platform,
            content=article.content or "",
            language=getattr(article, "language", "zh"),
        )

        raw = self._call_ai(prompt)
        parsed = self._parse_json_response(raw)
        demands = parsed.get("demands", [])

        for demand in demands:
            self._validate_demand(demand)
            score = demand.get("importance_score", 0)
            if score > 8:
                highlight_important(
                    f"High-importance demand detected: {demand.get('title')} "
                    f"(score={score})",
                    importance=score,
                )

        logger.info(
            "Extracted {} demands from article id={}",
            len(demands),
            article.id,
        )
        return demands

    def extract_from_comments(self, comments: List[HotComment]) -> List[Dict]:
        """Extract workplace demands from a list of hot comments.

        Args:
            comments: A sequence of :class:`HotComment` ORM instances.

        Returns:
            A list of demand dicts extracted from the comment text.

        Raises:
            ValueError: If the LLM response is not valid JSON or is missing
                the ``demands`` key.
        """
        comments_text = "\n".join(
            f"[{c.commenter or '匿名'}] (👍{c.like_count}): {c.content}"
            for c in comments
        )

        prompt = format_prompt(COMMENT_ANALYSIS_PROMPT, comments=comments_text)
        raw = self._call_ai(prompt)
        parsed = self._parse_json_response(raw)
        demands = parsed.get("demands", [])

        for demand in demands:
            self._validate_demand(demand)
            score = demand.get("importance_score", 0)
            if score > 8:
                highlight_important(
                    f"High-importance demand from comments: {demand.get('title')} "
                    f"(score={score})",
                    importance=score,
                )

        logger.info("Extracted {} demands from {} comments", len(demands), len(comments))
        return demands

    def analyze_batch(self, batch_size: Optional[int] = None) -> int:
        """Analyse a batch of unanalysed articles end-to-end.

        For each article the method:

        1. Extracts demands via :meth:`extract_from_article`.
        2. Persists each demand with :func:`save_demand`.
        3. Creates :class:`ArticleDemandRelation` records.
        4. Optionally extracts demands from the article's hot comments.
        5. Marks the article as analysed.

        Args:
            batch_size: Number of articles to process.  Falls back to the
                configured ``batch_size`` when *None*.

        Returns:
            The number of articles successfully analysed.
        """
        size = batch_size or self.batch_size
        articles = get_unanalyzed_articles(limit=size)

        if not articles:
            logger.info("No unanalyzed articles found")
            return 0

        analyzed_count = 0

        for article in articles:
            if self._call_count >= self.daily_budget:
                logger.warning(
                    "Daily API budget reached ({}/{}), stopping batch",
                    self._call_count,
                    self.daily_budget,
                )
                break

            try:
                demands = self.extract_from_article(article)

                with get_session() as session:
                    for demand_dict in demands:
                        # Convert tags list to JSON string for storage
                        tags = demand_dict.get("tags", [])
                        if isinstance(tags, list):
                            demand_dict["tags"] = json.dumps(tags, ensure_ascii=False)

                        saved_demand = save_demand(demand_dict)

                        relation = ArticleDemandRelation(
                            article_id=article.id,
                            demand_id=saved_demand.id,
                            relevance_score=demand_dict.get("importance_score", 0),
                            context_snippet=demand_dict.get("description", "")[:200],
                        )
                        session.add(relation)

                    # Extract from comments if available
                    if article.hot_comments:
                        unanalyzed_comments = [
                            c for c in article.hot_comments if not c.is_analyzed
                        ]
                        if unanalyzed_comments and self._call_count < self.daily_budget:
                            comment_demands = self.extract_from_comments(
                                unanalyzed_comments,
                            )
                            for cd in comment_demands:
                                tags = cd.get("tags", [])
                                if isinstance(tags, list):
                                    cd["tags"] = json.dumps(tags, ensure_ascii=False)
                                save_demand(cd)

                            for c in unanalyzed_comments:
                                c.is_analyzed = True
                                session.add(c)

                    # Mark article as analysed
                    article.is_analyzed = True
                    session.add(article)

                analyzed_count += 1
                logger.info(
                    "Analysed article id={} ({}/{})",
                    article.id,
                    analyzed_count,
                    len(articles),
                )

            except Exception:
                logger.exception("Failed to analyse article id={}", article.id)

        logger.info(
            "Batch complete — analysed {}/{} articles, total API calls: {}, "
            "total tokens: {}",
            analyzed_count,
            len(articles),
            self._call_count,
            self._total_tokens,
        )
        return analyzed_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_ai(self, prompt: str) -> str:
        """Send a prompt to the configured LLM provider and return the response.

        Implements retry logic (up to 3 attempts with exponential back-off)
        and tracks call count / token usage.

        Args:
            prompt: The fully-formatted prompt string.

        Returns:
            The raw text content of the LLM response.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                if self.provider == "anthropic":
                    result, tokens = self._call_anthropic(prompt)
                elif self.provider == "openai":
                    result, tokens = self._call_openai(prompt)
                elif self.provider == "ollama":
                    result, tokens = self._call_ollama(prompt)
                else:
                    raise ValueError(f"Unsupported AI provider: {self.provider}")

                self._call_count += 1
                self._total_tokens += tokens
                logger.debug(
                    "AI call #{} succeeded — {} tokens (attempt {}/{})",
                    self._call_count,
                    tokens,
                    attempt,
                    max_retries,
                )
                return result

            except Exception as exc:
                logger.warning(
                    "AI call failed (attempt {}/{}): {}",
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt == max_retries:
                    raise RuntimeError(
                        f"AI call failed after {max_retries} retries: {exc}"
                    ) from exc
                time.sleep(2 ** attempt)

        # Unreachable, but keeps mypy happy
        raise RuntimeError("AI call failed unexpectedly")  # pragma: no cover

    # -- Provider-specific helpers --------------------------------------

    def _call_anthropic(self, prompt: str) -> tuple[str, int]:
        """Call the Anthropic Messages API.

        Returns:
            A ``(response_text, token_count)`` tuple.
        """
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
        return text, tokens

    def _call_openai(self, prompt: str) -> tuple[str, int]:
        """Call the OpenAI ChatCompletion API.

        Returns:
            A ``(response_text, token_count)`` tuple.
        """
        import openai  # noqa: delayed import — optional dependency

        client = openai.OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens

    def _call_ollama(self, prompt: str) -> tuple[str, int]:
        """Call a local Ollama instance via its HTTP API.

        Returns:
            A ``(response_text, token_count)`` tuple.
        """
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
        tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        return text, tokens

    # -- Response parsing -----------------------------------------------

    def _parse_json_response(self, response: str) -> Dict:
        """Extract and parse JSON from an LLM response string.

        Handles responses wrapped in Markdown code fences
        (e.g. ````` ```json … ``` `````).

        Args:
            response: Raw LLM response text.

        Returns:
            The parsed dictionary.

        Raises:
            ValueError: If no valid JSON object can be extracted.
        """
        text = response.strip()

        # Strip markdown code fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        # Fallback: find the first top-level JSON object
        if not text.startswith("{"):
            brace_start = text.find("{")
            if brace_start == -1:
                raise ValueError("No JSON object found in AI response")
            text = text[brace_start:]

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON from AI response: {exc}") from exc

    # -- Validation -----------------------------------------------------

    @staticmethod
    def _validate_demand(demand: Dict) -> None:
        """Validate that a demand dict contains the required fields.

        Performs light normalisation (e.g. clamping *importance_score* to
        0–10) and warns when the ``category`` is not in
        :data:`VALID_CATEGORIES`.

        Args:
            demand: A single demand dictionary returned by the LLM.

        Raises:
            ValueError: If the *title* field is missing.
        """
        if not demand.get("title"):
            raise ValueError("Demand missing required field: title")

        # Clamp importance_score to [0, 10]
        score = demand.get("importance_score", 0)
        demand["importance_score"] = max(0, min(10, float(score)))

        # Warn on unknown category
        category = demand.get("category", "")
        if category and category not in VALID_CATEGORIES:
            logger.warning(
                "Unknown demand category '{}', expected one of: {}",
                category,
                VALID_CATEGORIES,
            )

        # Ensure tags is a list
        tags = demand.get("tags")
        if tags is None:
            demand["tags"] = []
        elif isinstance(tags, str):
            demand["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
