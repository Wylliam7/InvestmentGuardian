"""État AWS : détection d'identifiants (sans réseau Bedrock) et test de connexion à la demande."""
from __future__ import annotations

import os

from guardian.agent.agent import DEFAULT_MODEL_ID, DEFAULT_REGION, map_error


def credentials_status() -> dict:
    """Indique si la chaîne d'identifiants boto3 en trouve, sans jamais exposer leur valeur."""
    try:
        import boto3
        session = boto3.Session()
        creds = session.get_credentials()
        return {"credentials_found": creds is not None,
                "source": getattr(creds, "method", None) if creds else None,
                "region": session.region_name or os.environ.get("AWS_REGION", DEFAULT_REGION)}
    except Exception as e:  # noqa: BLE001
        return {"credentials_found": False, "source": None, "region": DEFAULT_REGION, "error": map_error(e)["detail"]}


def test_bedrock_connection(model_id: str | None = None, region: str | None = None) -> dict:
    """Une seule requête Converse minimale (quelques jetons)."""
    import boto3
    mid = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    reg = region or os.environ.get("AWS_REGION", DEFAULT_REGION)
    try:
        client = boto3.client("bedrock-runtime", region_name=reg)
        client.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Réponds : ok"}]}],
                        inferenceConfig={"maxTokens": 8, "temperature": 0.0})
        return {"ok": True, "model_id": mid, "region": reg}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "model_id": mid, "region": reg, "error": map_error(e)}
