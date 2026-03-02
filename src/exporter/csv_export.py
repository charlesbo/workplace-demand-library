"""CSV exporter for workplace demands."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.storage.database import get_session
from src.storage.models import Demand
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLUMNS = ["ID", "标题", "分类", "子分类", "频次", "重要性", "趋势", "状态", "首次发现", "最后发现", "标签"]


class CsvExporter:
    """Export workplace demands to a UTF-8 BOM CSV file."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def export(self, output_path: Optional[str] = None) -> str:
        """Export all demands to a CSV file.

        The file uses UTF-8 with BOM so that Microsoft Excel opens it
        correctly with CJK characters.

        Args:
            output_path: Destination file path.  Defaults to
                ``<export.output_dir>/demands_YYYYMMDD.csv``.

        Returns:
            The absolute path of the generated CSV file.
        """
        if output_path is None:
            output_dir = Path(self.settings.get("export.output_dir", "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"demands_{datetime.now():%Y%m%d}.csv")
        else:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        demands = self._load_data()

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            for d in demands:
                writer.writerow(self._demand_to_row(d))

        logger.info(f"CSV exported: {output_path} ({len(demands)} demands)")
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_data() -> list[Demand]:
        """Load all demands ordered by frequency descending."""
        with get_session() as session:
            demands = (
                session.query(Demand).order_by(Demand.frequency.desc()).all()
            )
            session.expunge_all()
        return demands

    @staticmethod
    def _demand_to_row(d: Demand) -> list:
        """Convert a Demand instance to a flat CSV row."""
        tags = ""
        if d.tags:
            try:
                tags = ", ".join(json.loads(d.tags))
            except (json.JSONDecodeError, TypeError):
                tags = d.tags
        return [
            d.id,
            d.title,
            d.category or "",
            d.subcategory or "",
            d.frequency,
            round(d.importance_score, 2),
            d.trend,
            d.status,
            d.first_seen.strftime("%Y-%m-%d") if d.first_seen else "",
            d.last_seen.strftime("%Y-%m-%d") if d.last_seen else "",
            tags,
        ]
