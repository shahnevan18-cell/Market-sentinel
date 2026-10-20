"""Shared state for one investigation (the evidence store).

Tools write their results here, so the rubric, the strategist and the report
all read exactly the evidence that the investigator saw.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from analytics.anomaly_detection import ScanResult
from config.settings import Settings
from providers.market_data import MarketDataset
from providers.news_data import NOT_SEARCHED, NewsItem, NewsService, ProviderStatus


@dataclass
class InvestigationContext:
    event: dict
    scan: ScanResult
    dataset: MarketDataset
    settings: Settings
    news_service: NewsService
    historical: bool = False
    prev_session: pd.Timestamp | None = None
    news_cutoff: datetime | None = None
    evidence: dict = field(default_factory=dict)
    news_items: dict[str, NewsItem] = field(default_factory=dict)
    news_statuses: list[ProviderStatus] = field(default_factory=list)
    news_queries: list[str] = field(default_factory=list)
    assessments: dict[str, dict] = field(default_factory=dict)
    rubric: object | None = None
    warnings: list[str] = field(default_factory=list)
    official_links: list[dict] = field(default_factory=list)   # NSE/BSE pages for manual checking (link-only)

    @property
    def ticker(self) -> str:
        return self.event["ticker"]

    @property
    def date(self) -> pd.Timestamp:
        return pd.Timestamp(self.event["date"])

    @property
    def universe(self):
        return self.scan.universe

    def final_relevance(self, item: NewsItem) -> tuple[str, str, str]:
        """(relevance, basis, rationale) using the LLM's judgement when it gave one."""
        a = self.assessments.get(item.source_id)
        if a:
            return a["relevance"], a.get("basis", "LLM judgement"), a.get("rationale", "")
        return item.relevance, item.relevance_basis, item.relevance_rationale

    def news_available(self) -> bool:
        attempted = [s for s in self.news_statuses if s.status not in NOT_SEARCHED]
        return any(s.status in ("ok", "empty") for s in attempted)

    def news_all_failed(self) -> bool:
        """True when every source that was actually searched failed. Link-only entries (official NSE/BSE pages)
        are not searches, so they must not hide a failure of the news providers."""
        attempted = [s for s in self.news_statuses if s.status not in NOT_SEARCHED]
        return bool(attempted) and all(s.status == "failed" for s in attempted)

    def news_searched(self) -> bool:
        return bool(self.news_statuses)
