"""Loads YAML config and secrets from the environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field

from hunter.models import ListingKind, PropertyType

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class School(BaseModel):
    name: str
    lat: float
    lng: float


class PropertyCriteria(BaseModel):
    types: list[PropertyType] = Field(default_factory=lambda: list(PropertyType))
    min_beds: int | None = None
    min_baths: int | None = None
    min_land_m2: float | None = None


class BudgetCriteria(BaseModel):
    max: int | None = None  # filled from BUDGET_MAX
    tolerance: float = 0.05
    estimate_rule: Literal["optimistic", "mid", "conservative"] = "mid"
    include_unknown_price: bool = True


class WalkRule(BaseModel):
    type: Literal["walk"]
    max_minutes: float


class DriveRule(BaseModel):
    type: Literal["drive"]
    max_minutes: float


class TrainStopsRule(BaseModel):
    type: Literal["train_stops"]
    school_station: str
    max_stops: int
    max_walk_to_station_minutes: float


DistanceRule = Annotated[WalkRule | DriveRule | TrainStopsRule, Field(discriminator="type")]


class LlmConfig(BaseModel):
    model: str = "gemini-flash-latest"
    max_calls_per_run: int = 200


class Criteria(BaseModel):
    school: School
    suburbs: list[str]
    property: PropertyCriteria = Field(default_factory=PropertyCriteria)
    budget: BudgetCriteria = Field(default_factory=BudgetCriteria)
    distance_rules: list[DistanceRule] = Field(default_factory=list)
    llm: LlmConfig = Field(default_factory=LlmConfig)


class Stations(BaseModel):
    stations: dict[str, tuple[float, float]]
    lines: dict[str, list[str]]


class Source(BaseModel):
    name: str
    agency: str
    enabled: bool = True
    run_on: Literal["actions", "local"] = "actions"
    fetch: Literal["httpx", "playwright"] = "httpx"
    adapter: str = "generic"
    list_urls: list[str] = Field(default_factory=list)
    kind_hint: ListingKind | None = None  # set when every listing on these pages has one kind
    detail_link_selector: str | None = None
    max_details: int = 60
    options: dict[str, Any] = Field(default_factory=dict)  # adapter-specific settings
    notes: str | None = None


class Sources(BaseModel):
    sources: list[Source]


class Secrets(BaseModel):
    gemini_api_key: str | None = None
    ors_api_key: str | None = None
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_refresh_token: str | None = None
    notify_email: str | None = None
    callmebot_phone: str | None = None
    callmebot_apikey: str | None = None

    @property
    def gmail_ready(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)

    @classmethod
    def from_env(cls) -> Secrets:
        return cls(**{name: os.environ.get(name.upper()) or None for name in cls.model_fields})


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_criteria(config_dir: Path = CONFIG_DIR) -> Criteria:
    criteria = Criteria.model_validate(_load(config_dir / "criteria.yaml"))
    if budget := os.environ.get("BUDGET_MAX"):
        criteria.budget.max = int(budget.replace(",", "").replace("_", ""))
    return criteria


def load_stations(config_dir: Path = CONFIG_DIR) -> Stations:
    return Stations.model_validate(_load(config_dir / "stations.yaml"))


def load_sources(config_dir: Path = CONFIG_DIR) -> list[Source]:
    return Sources.model_validate(_load(config_dir / "sources.yaml")).sources
