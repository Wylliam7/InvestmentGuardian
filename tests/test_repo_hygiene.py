"""Aucune donnée sensible ni donnée officielle dans les fichiers suivis (ou suivables) par Git."""
import re
import subprocess

import pytest

from conftest import REPO

PATTERNS = {
    "clé d'accès AWS": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "clé secrète AWS affectée": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{20,}"),
    "jeton de session AWS affecté": re.compile(r"(?i)aws_session_token\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{30,}"),
    "clé API Kiro": re.compile(r"\bkak_[A-Za-z0-9]{16,}\b"),
    "jeton GitHub": re.compile(r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}\b|github_pat_[A-Za-z0-9_]{30,}"),
    "clé privée": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jeton Slack": re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}"),
}


def candidate_files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO, capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if (REPO / f).is_file()]


def test_no_secret_patterns_in_tracked_or_trackable_files():
    hits = []
    for f in candidate_files():
        try:
            text = (REPO / f).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pat in PATTERNS.items():
            if pat.search(text):
                hits.append(f"{f} : {name}")
    assert not hits, hits


def test_sensitive_and_official_data_files_are_not_trackable():
    files = candidate_files()
    forbidden = [f for f in files if f == ".env" or f.startswith(".env.") and f != ".env.example" or f.endswith(".csv")
                 or f.startswith("Datathon2026/") or f.startswith(".venv/") or (f.startswith("traces/") and f != "traces/.gitkeep")
                 or f.endswith((".pem", ".key"))]
    assert not forbidden, forbidden
    assert ".env.example" in files and "config/guardian_rules.yaml" in files


def test_env_example_contains_names_only():
    for line in (REPO / ".env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert name.isupper() and not re.search(r"(ACCESS_KEY|SECRET|SESSION_TOKEN|API_KEY|PASSWORD|_TOKEN$)", name), line
            assert len(value) < 40, line


def test_no_aws_credentials_hardcoded_in_python_sources():
    for f in candidate_files():
        if f.endswith(".py"):
            text = (REPO / f).read_text(encoding="utf-8")
            assert "aws_access_key_id=" not in text.lower().replace(" ", "") or "test" in f, f
