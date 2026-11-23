"""Gemini AI incident explanations (backend only).

- Called ONLY when >=1 anomaly is detected AND a new alert is being created
  (dedup bumps never call the AI).
- Only metadata is sent to Gemini: monitor name/method/host, status code,
  timings, anomaly types, baseline stats. Response bodies are NEVER sent.
- Output is strict JSON validated by Pydantic. On ANY failure (no key,
  network, quota, bad JSON) a deterministic fallback template is used, so
  monitoring never fails because of AI.
"""
from __future__ import annotations

import json
from typing import Callable, Literal

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger, sanitize_url
from app.models.monitor import Monitor
from app.services.anomaly_service import AnomalyFinding
from app.services.http_client import build_async_client

logger = get_logger("ai")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
SEVERITIES = ("info", "warning", "high", "critical")


class AIAlertContent(BaseModel):
    title: str
    severity: Literal["info", "warning", "high", "critical"]
    summary: str
    possible_cause: str
    recommended_action: str


# Deterministic fallback templates. {monitor_name} and {detail} are filled in
# from the finding; severity always comes from the finding itself.
FALLBACK_TEMPLATES: dict[str, dict[str, str]] = {
    "HIGH_RESPONSE_TIME": {
        "title": "High response time on {monitor_name}",
        "summary": "The API responded slowly. {detail}",
        "possible_cause": (
            "The upstream service may be under load, a downstream dependency "
            "may be slow, or the network path may be degraded."
        ),
        "recommended_action": (
            "Check the upstream service's own status and latency, then review "
            "recent deploys or traffic spikes on that endpoint."
        ),
    },
    "HTTP_ERROR": {
        "title": "HTTP error on {monitor_name}",
        "summary": "The API returned an error status. {detail}",
        "possible_cause": (
            "The endpoint may be failing server-side, the request may be "
            "invalid, or the service may be partially down."
        ),
        "recommended_action": (
            "Reproduce the request manually, check the service's error logs, "
            "and confirm the endpoint URL and credentials are still valid."
        ),
    },
    "TIMEOUT": {
        "title": "Timeout on {monitor_name}",
        "summary": "The API did not respond in time. {detail}",
        "possible_cause": (
            "The service may be down, overloaded, or blocked by a slow "
            "dependency; a network problem is also possible."
        ),
        "recommended_action": (
            "Check whether the service is reachable at all, then look at its "
            "load and dependency health. Consider raising the timeout only "
            "after the cause is understood."
        ),
    },
    "NETWORK_ERROR": {
        "title": "Cannot reach {monitor_name}",
        "summary": "The API could not be reached — no response was received. {detail}",
        "possible_cause": (
            "The host may be down, the DNS name may no longer resolve, a "
            "firewall may be blocking the request, or the TLS certificate "
            "may be invalid."
        ),
        "recommended_action": (
            "Check the host from another network (ping / curl), confirm the "
            "DNS record and certificate, and verify no firewall or proxy "
            "rule is blocking outbound requests."
        ),
    },
    "ZERO_RECORDS": {
        "title": "Zero records from {monitor_name}",
        "summary": "The API returned a successful response with no records. {detail}",
        "possible_cause": (
            "The underlying data source may be empty, a filter may have "
            "changed, or an upstream sync may have failed."
        ),
        "recommended_action": (
            "Verify the data source still holds records and that query "
            "parameters or filters have not changed upstream."
        ),
    },
    "INVALID_RESPONSE": {
        "title": "Invalid response from {monitor_name}",
        "summary": "The API response could not be parsed as JSON. {detail}",
        "possible_cause": (
            "The endpoint may be returning an HTML error page, a proxy may be "
            "intercepting the request, or the API format may have changed."
        ),
        "recommended_action": (
            "Fetch the endpoint manually and inspect the raw response and "
            "Content-Type header."
        ),
    },
    "MISSING_FIELDS": {
        "title": "Missing fields in {monitor_name} response",
        "summary": "Expected fields were absent from the API response. {detail}",
        "possible_cause": (
            "The API schema may have changed, or the endpoint may be returning "
            "a different payload shape than before."
        ),
        "recommended_action": (
            "Compare the current response payload against the expected schema "
            "and update the monitor's expected fields if the change is "
            "intentional."
        ),
    },
    "LARGE_RESPONSE": {
        "title": "Large response from {monitor_name}",
        "summary": "The API response exceeded the configured size limit. {detail}",
        "possible_cause": (
            "The dataset behind the endpoint may have grown, pagination may "
            "have been removed, or the response may include extra data."
        ),
        "recommended_action": (
            "Check whether the endpoint still paginates, and raise the size "
            "limit only if the growth is legitimate."
        ),
    },
    "UNEXPECTED_STATUS": {
        "title": "Unexpected status from {monitor_name}",
        "summary": "The API returned a status outside the expected set. {detail}",
        "possible_cause": (
            "The endpoint may have moved (redirect), its behaviour may have "
            "changed, or a proxy may be altering the response."
        ),
        "recommended_action": (
            "Fetch the endpoint manually, follow any redirects, and update "
            "the expected status codes if the new status is correct."
        ),
    },
    "HISTORICAL_ANOMALY": {
        "title": "Unusual latency on {monitor_name}",
        "summary": "Response time deviated significantly from its recent history. {detail}",
        "possible_cause": (
            "A recent deploy, traffic change, or degrading dependency may "
            "have shifted the endpoint's latency profile."
        ),
        "recommended_action": (
            "Compare latency before and after the most recent deploy and "
            "check the service's resource usage."
        ),
    },
    "_DEFAULT": {
        "title": "Anomaly on {monitor_name}",
        "summary": "An anomaly was detected. {detail}",
        "possible_cause": "See the anomaly description for details.",
        "recommended_action": "Inspect the monitor's recent checks for context.",
    },
}


def fallback_content(monitor_name: str, finding: AnomalyFinding) -> AIAlertContent:
    template = FALLBACK_TEMPLATES.get(finding.anomaly_type, FALLBACK_TEMPLATES["_DEFAULT"])
    severity = finding.severity if finding.severity in SEVERITIES else "warning"
    return AIAlertContent(
        title=template["title"].format(monitor_name=monitor_name),
        severity=severity,  # type: ignore[arg-type]
        summary=template["summary"].format(monitor_name=monitor_name, detail=finding.description),
        possible_cause=template["possible_cause"],
        recommended_action=template["recommended_action"],
    )


def build_prompt(monitor: Monitor, finding: AnomalyFinding, metrics: dict) -> str:
    """Metadata-only prompt. Response bodies are never included."""
    baseline = metrics.get("baseline")
    baseline_line = (
        f"- Baseline (last {baseline['n']} checks): mean {baseline['mean_ms']:.0f}ms, "
        f"stddev {baseline['stddev_ms']:.0f}ms."
        if baseline
        else "- Baseline: not enough history yet."
    )
    return (
        "You are PulseWatch AI, an assistant that explains API monitoring "
        "anomalies to developers.\n\n"
        "Facts about this incident (do not invent any other metrics):\n"
        f"- Monitor: {monitor.name} ({monitor.method} {sanitize_url(monitor.url)})\n"
        f"- Status code: {metrics.get('status_code')}\n"
        f"- Response time: {metrics.get('response_time_ms')} ms "
        f"(threshold {monitor.latency_threshold_ms} ms)\n"
        f"- Response size: {metrics.get('response_size_bytes')} bytes\n"
        f"- Records returned: {metrics.get('records_returned')}\n"
        f"- Anomaly: {finding.anomaly_type} (severity {finding.severity}) — "
        f"{finding.description}\n"
        f"{baseline_line}\n\n"
        "Rules:\n"
        "- Never invent metrics, dates, or causes not supported by the facts above.\n"
        "- Clearly distinguish facts from hypotheses.\n"
        "- Be concise and developer-oriented: one short summary, one most "
        "likely cause, one concrete recommended action.\n\n"
        "Return STRICT JSON only, with exactly these keys: title, severity "
        "(one of info, warning, high, critical), summary, possible_cause, "
        "recommended_action."
    )


async def generate_alert_content(
    monitor: Monitor,
    finding: AnomalyFinding,
    metrics: dict,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> tuple[AIAlertContent, bool]:
    """Generate alert content via Gemini, or a deterministic fallback.

    Returns ``(content, ai_generated)``. Never raises: any failure falls back
    to the template for the anomaly type.
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return fallback_content(monitor.name, finding), False
    try:
        gemini_url = f"{GEMINI_API_BASE}/{settings.GEMINI_MODEL}:generateContent"
        client = (
            client_factory()
            if client_factory
            else build_async_client(gemini_url, timeout=30.0)
        )
        try:
            url = gemini_url
            payload = {
                "contents": [{"parts": [{"text": build_prompt(monitor, finding, metrics)}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
            }
            response = await client.post(
                url, json=payload, headers={"x-goog-api-key": api_key}
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            content = AIAlertContent.model_validate(json.loads(text))
            logger.info(
                "Gemini alert content generated monitor_id=%s anomaly=%s",
                monitor.id,
                finding.anomaly_type,
            )
            return content, True
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001 - any Gemini failure falls back
        logger.warning(
            "Gemini call failed (%s); using fallback template monitor_id=%s anomaly=%s",
            type(exc).__name__,
            monitor.id,
            finding.anomaly_type,
        )
        return fallback_content(monitor.name, finding), False
