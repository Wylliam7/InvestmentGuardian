"""Chargement et validation des CSV officiels (lecture seule)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "Datathon2026" / "alphaforge_starter"

UNIVERSE_COLS = ["asset_id", "ticker", "name", "asset_class", "market", "currency", "sector"]
PRICE_COLS = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "currency"]
FX_COLS = ["date", "usdcad", "cadusd"]


class DataError(Exception):
    """Données absentes, mal formées ou incohérentes."""


@dataclass(frozen=True)
class DataBundle:
    data_dir: Path
    universe: pd.DataFrame          # index = ticker
    prices: pd.DataFrame            # format long, dates en datetime64
    fx: pd.Series                   # USD/CAD, index = date
    sha256: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    manifest_mismatch: tuple = ()   # fichiers dont l'empreinte diffère de l'audit


def resolve_data_dir(data_dir: str | os.PathLike | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    env = os.environ.get("GUARDIAN_DATA_DIR")
    return Path(env) if env else DEFAULT_DATA_DIR


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise DataError(f"{name} : colonnes manquantes {missing}")


def _read_manifest() -> dict:
    path = REPO_ROOT / "config" / "data_manifest.yaml"
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sha256", {})


def load_bundle(data_dir: str | os.PathLike | None = None, check_manifest: bool = True) -> DataBundle:
    """Charge assets_universe, prices_daily et fx_usdcad_daily ; valide leur cohérence.

    Les fichiers ne sont jamais modifiés. Lève DataError si un contrôle échoue.
    """
    d = resolve_data_dir(data_dir)
    names = ["assets_universe.csv", "prices_daily.csv", "fx_usdcad_daily.csv"]
    for n in names:
        if not (d / n).is_file():
            raise DataError(f"Fichier introuvable : {d / n}. Placez les CSV officiels dans ce dossier "
                            f"ou définissez GUARDIAN_DATA_DIR.")
    sha = {n: sha256_file(d / n) for n in names}

    try:
        universe = pd.read_csv(d / "assets_universe.csv")
        prices = pd.read_csv(d / "prices_daily.csv")
        fx = pd.read_csv(d / "fx_usdcad_daily.csv")
    except Exception as e:  # noqa: BLE001
        raise DataError(f"Lecture des CSV impossible : {e}") from e

    _require_columns(universe, UNIVERSE_COLS, "assets_universe.csv")
    _require_columns(prices, PRICE_COLS, "prices_daily.csv")
    _require_columns(fx, FX_COLS, "fx_usdcad_daily.csv")

    if universe["ticker"].duplicated().any():
        raise DataError("assets_universe.csv : tickers dupliqués")
    prices["date"] = pd.to_datetime(prices["date"], errors="raise")
    fx["date"] = pd.to_datetime(fx["date"], errors="raise")

    if prices.duplicated(["date", "ticker"]).any():
        raise DataError("prices_daily.csv : doublons (date, ticker)")
    if prices["adj_close"].isna().any() or (prices["adj_close"] <= 0).any():
        raise DataError("prices_daily.csv : adj_close manquant ou non positif")
    unknown = set(prices["ticker"]) - set(universe["ticker"])
    if unknown:
        raise DataError(f"prices_daily.csv : tickers absents de l'univers {sorted(unknown)}")
    cur = prices.merge(universe[["ticker", "currency"]], on="ticker", suffixes=("", "_u"))
    if (cur["currency"] != cur["currency_u"]).any():
        raise DataError("Incohérence de devise entre prices_daily.csv et assets_universe.csv")
    if fx["date"].duplicated().any() or not fx["date"].is_monotonic_increasing:
        raise DataError("fx_usdcad_daily.csv : dates dupliquées ou non triées")
    if fx["usdcad"].isna().any() or (fx["usdcad"] <= 0).any():
        raise DataError("fx_usdcad_daily.csv : taux manquant ou non positif")

    mismatch: tuple = ()
    if check_manifest:
        expected = _read_manifest()
        mismatch = tuple(n for n in names if n in expected and expected[n] != sha[n])

    return DataBundle(
        data_dir=d,
        universe=universe.set_index("ticker"),
        prices=prices.sort_values(["ticker", "date"]).reset_index(drop=True),
        fx=fx.set_index("date")["usdcad"].astype(float),
        sha256=sha,
        rows={"assets_universe.csv": len(universe), "prices_daily.csv": len(prices),
              "fx_usdcad_daily.csv": len(fx)},
        manifest_mismatch=mismatch,
    )
