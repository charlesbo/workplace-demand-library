"""Trend detection module for workplace demand analysis.

Detects rising, declining, and emerging demands by analyzing
historical snapshot data and week-over-week frequency changes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select

from src.analyzer.prompts import TREND_ANALYSIS_PROMPT, format_prompt
from src.storage.database import get_session
from src.storage.models import Demand, TrendSnapshot
from src.utils.config import get_settings
from src.utils.logger import get_logger


class TrendDetector:
    """Detect and analyze trends in workplace demands."""

    def __init__(self) -> None:
        """Initialize trend detector with logger and settings."""
        self.logger = get_logger(__name__)
        self.settings = get_settings()

    def create_snapshot(self) -> int:
        """Record current frequency and heat_score for all demands.

        Creates a TrendSnapshot for each demand in the database
        with today's date.

        Returns:
            Number of snapshots created.
        """
        today = date.today()
        count = 0

        with get_session() as session:
            demands = session.execute(select(Demand)).scalars().all()

            for demand in demands:
                snapshot = TrendSnapshot(
                    demand_id=demand.id,
                    snapshot_date=today,
                    frequency=demand.frequency,
                    heat_score=demand.importance_score,
                )
                session.add(snapshot)
                count += 1

            self.logger.info(f"Created {count} trend snapshots for {today}")

        return count

    def detect_trends(self) -> Dict:
        """Detect week-over-week trends for all demands.

        Compares the last two weekly snapshots to calculate change
        rates and classifies each demand as rising, declining, or
        stable. Updates the demand.trend field in the database.

        Returns:
            Summary dict with keys: rising, declining, stable, new_demands.
        """
        summary: Dict[str, list] = {
            "rising": [],
            "declining": [],
            "stable": [],
            "new_demands": [],
        }

        with get_session() as session:
            # Get the two most recent distinct snapshot dates
            dates_stmt = (
                select(TrendSnapshot.snapshot_date)
                .distinct()
                .order_by(TrendSnapshot.snapshot_date.desc())
                .limit(2)
            )
            dates = session.execute(dates_stmt).scalars().all()

            if len(dates) < 2:
                self.logger.warning("Not enough snapshots for trend detection")
                return summary

            current_date, previous_date = dates[0], dates[1]

            # Load snapshots keyed by demand_id
            current_snaps = {
                s.demand_id: s
                for s in session.execute(
                    select(TrendSnapshot).where(
                        TrendSnapshot.snapshot_date == current_date
                    )
                ).scalars().all()
            }
            previous_snaps = {
                s.demand_id: s
                for s in session.execute(
                    select(TrendSnapshot).where(
                        TrendSnapshot.snapshot_date == previous_date
                    )
                ).scalars().all()
            }

            demands = session.execute(select(Demand)).scalars().all()

            for demand in demands:
                current = current_snaps.get(demand.id)
                previous = previous_snaps.get(demand.id)

                if current and not previous:
                    demand.trend = "rising"
                    summary["new_demands"].append(demand.title)
                elif current and previous:
                    change_rate = self._calculate_change_rate(
                        previous.frequency, current.frequency
                    )

                    if change_rate > 0.2:
                        demand.trend = "rising"
                        summary["rising"].append(demand.title)
                    elif change_rate < -0.2:
                        demand.trend = "declining"
                        summary["declining"].append(demand.title)
                    else:
                        demand.trend = "stable"
                        summary["stable"].append(demand.title)

            self.logger.info(
                f"Trend detection complete: "
                f"{len(summary['rising'])} rising, "
                f"{len(summary['declining'])} declining, "
                f"{len(summary['stable'])} stable, "
                f"{len(summary['new_demands'])} new"
            )

        return summary

    def detect_emerging_demands(self, days: int = 7) -> List[Demand]:
        """Find recently appeared demands with high importance.

        Args:
            days: Look-back window in days (default 7).

        Returns:
            List of Demand objects first seen within the window
            and with importance_score > 5.
        """
        cutoff = datetime.now() - timedelta(days=days)

        with get_session() as session:
            stmt = select(Demand).where(
                Demand.first_seen >= cutoff,
                Demand.importance_score > 5,
            )
            emerging = session.execute(stmt).scalars().all()

            self.logger.info(
                f"Found {len(emerging)} emerging demands in last {days} days"
            )

        return emerging

    def generate_trend_report(self, period: str = "week") -> str:
        """Generate an AI-powered markdown trend report.

        Args:
            period: Analysis period, e.g. 'week' or 'month'.

        Returns:
            Formatted markdown report string.
        """
        summary = self.detect_trends()
        emerging = self.detect_emerging_demands()

        trend_data = {
            "period": period,
            "rising": summary["rising"],
            "declining": summary["declining"],
            "stable": summary["stable"],
            "new_demands": summary["new_demands"],
            "emerging": [d.title for d in emerging],
        }

        prompt = format_prompt(TREND_ANALYSIS_PROMPT, **trend_data)

        settings = self.settings
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.get("api_key", ""),
            base_url=settings.get("base_url", None),
        )

        response = client.chat.completions.create(
            model=settings.get("model", "gpt-4"),
            messages=[{"role": "user", "content": prompt}],
        )

        report = response.choices[0].message.content
        self.logger.info(f"Generated trend report for period: {period}")
        return report

    def get_trend_data(self, demand_id: int, periods: int = 12) -> List[Dict]:
        """Get historical snapshot data for a specific demand.

        Args:
            demand_id: ID of the demand to query.
            periods: Maximum number of snapshots to return.

        Returns:
            List of dicts with keys: date, frequency, heat_score.
        """
        with get_session() as session:
            stmt = (
                select(TrendSnapshot)
                .where(TrendSnapshot.demand_id == demand_id)
                .order_by(TrendSnapshot.snapshot_date.desc())
                .limit(periods)
            )
            snapshots = session.execute(stmt).scalars().all()

        return [
            {
                "date": s.snapshot_date.isoformat(),
                "frequency": s.frequency,
                "heat_score": s.heat_score,
            }
            for s in reversed(snapshots)
        ]

    def _calculate_change_rate(self, old_val: float, new_val: float) -> float:
        """Calculate the relative change rate between two values.

        Args:
            old_val: Previous value.
            new_val: Current value.

        Returns:
            Fractional change rate (e.g. 0.25 means +25%).
            Returns 1.0 when old_val is 0 and new_val > 0,
            or 0.0 when both are 0.
        """
        if old_val == 0:
            return 1.0 if new_val > 0 else 0.0
        return (new_val - old_val) / old_val
