from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import timezone
from email.message import EmailMessage
from typing import Any

import httpx

from .models import MarketRecord, MatchResult
from .settings import Settings
from .text import isoformat, utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationOutcome:
    channel: str
    status: str
    detail: str = ""


def _slack_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(value: float | None) -> str:
    if value is None:
        return "not reported"
    return f"${value:,.0f}"


def _percent(value: float | None) -> str:
    if value is None:
        return "not reported"
    return f"{value * 100:.1f}%"


def _when(value: Any) -> str:
    if value is None:
        return "not reported"
    try:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except AttributeError:
        return str(value)


def build_payload(market: MarketRecord, match: MatchResult) -> dict[str, Any]:
    return {
        "event_type": "prediction_market_reference_detected",
        "detected_at": isoformat(utcnow()),
        "organization": match.organization,
        "severity": match.severity,
        "risk_score": match.risk_score,
        "matched_identity_terms": match.matched_identity_terms,
        "matched_metric_terms": match.matched_metric_terms,
        "risk_categories": match.categories,
        "likely_organization_roles": match.roles,
        "reasons": match.reasons,
        "review_questions": match.review_questions,
        "recommended_stakeholders": match.stakeholders,
        "recommended_actions": match.actions,
        "market": {
            "source": market.source,
            "external_id": market.external_id,
            "title": market.title,
            "description": market.description,
            "url": market.url,
            "status": market.status,
            "created_at": isoformat(market.created_at),
            "closes_at": isoformat(market.closes_at),
            "probability": market.probability,
            "volume": market.volume,
            "volume_24h": market.volume_24h,
            "liquidity": market.liquidity,
            "open_interest": market.open_interest,
        },
    }


def build_plain_text(market: MarketRecord, match: MatchResult) -> str:
    roles = ", ".join(match.roles) or "Referenced organization"
    reasons = "\n".join(f"- {item}" for item in match.reasons)
    questions = "\n".join(f"- {item}" for item in match.review_questions)
    actions = "\n".join(f"- {item}" for item in match.actions[:8])
    stakeholders = ", ".join(match.stakeholders) or "Risk"
    return f"""RaaScal Watch alert: {match.organization}

Severity: {match.severity.upper()} ({match.risk_score}/100)
Source: {market.source}
Contract: {market.title}
Probability: {_percent(market.probability)}
Volume: {_money(market.volume)}
Closes: {_when(market.closes_at)}
Link: {market.url or 'not available'}

Likely organization role(s): {roles}

Why it matched:
{reasons}

Questions to answer:
{questions}

Suggested owners: {stakeholders}

Contract-specific review steps:
{actions}

This alert is an external risk signal, not proof of manipulation or abuse.
"""


class AlertDispatcher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    @property
    def configured_channels(self) -> tuple[str, ...]:
        channels: list[str] = []
        if self.settings.slack_webhook_url:
            channels.append("slack")
        if self.settings.generic_webhook_url:
            channels.append("webhook")
        if (
            self.settings.smtp_host
            and self.settings.smtp_from
            and self.settings.smtp_to
        ):
            channels.append("email")
        return tuple(channels)

    async def send(
        self, market: MarketRecord, match: MatchResult
    ) -> list[NotificationOutcome]:
        logger.warning("\n%s", build_plain_text(market, match))
        outcomes = [NotificationOutcome("console", "sent")]
        tasks: list[asyncio.Task[NotificationOutcome]] = []
        if self.settings.slack_webhook_url:
            tasks.append(asyncio.create_task(self._send_slack(market, match)))
        if self.settings.generic_webhook_url:
            tasks.append(asyncio.create_task(self._send_webhook(market, match)))
        if (
            self.settings.smtp_host
            and self.settings.smtp_from
            and self.settings.smtp_to
        ):
            tasks.append(asyncio.create_task(self._send_email(market, match)))
        if tasks:
            outcomes.extend(await asyncio.gather(*tasks))
        return outcomes

    async def _send_slack(
        self, market: MarketRecord, match: MatchResult
    ) -> NotificationOutcome:
        assert self.settings.slack_webhook_url
        title = _slack_escape(market.title)
        role_line = ", ".join(match.roles) or "Referenced organization"
        reason_lines = "\n".join(f"• {_slack_escape(item)}" for item in match.reasons[:4])
        question_lines = "\n".join(
            f"• {_slack_escape(item)}" for item in match.review_questions[:3]
        )
        payload = {
            "text": f"RaaScal Watch: {match.organization} referenced on {market.source}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{match.severity.upper()} · {match.organization} referenced",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*<{market.url}|{title}>*\n"
                            f"Source: `{market.source}` · Risk score: *{match.risk_score}/100*\n"
                            f"Probability: {_percent(market.probability)} · "
                            f"Volume: {_money(market.volume)} · Closes: {_when(market.closes_at)}"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Likely organization role*\n{_slack_escape(role_line)}\n\n"
                            f"*Why it surfaced*\n{reason_lines}"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Questions to answer*\n{question_lines}",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "External risk signal only; not proof of manipulation or abuse.",
                        }
                    ],
                },
            ],
        }
        try:
            response = await self.client.post(self.settings.slack_webhook_url, json=payload)
            response.raise_for_status()
            return NotificationOutcome("slack", "sent")
        except Exception as exc:
            logger.exception("Slack notification failed")
            return NotificationOutcome("slack", "failed", str(exc))

    async def _send_webhook(
        self, market: MarketRecord, match: MatchResult
    ) -> NotificationOutcome:
        assert self.settings.generic_webhook_url
        try:
            response = await self.client.post(
                self.settings.generic_webhook_url,
                json=build_payload(market, match),
            )
            response.raise_for_status()
            return NotificationOutcome("webhook", "sent")
        except Exception as exc:
            logger.exception("Generic webhook notification failed")
            return NotificationOutcome("webhook", "failed", str(exc))

    async def _send_email(
        self, market: MarketRecord, match: MatchResult
    ) -> NotificationOutcome:
        try:
            await asyncio.to_thread(self._send_email_sync, market, match)
            return NotificationOutcome("email", "sent")
        except Exception as exc:
            logger.exception("Email notification failed")
            return NotificationOutcome("email", "failed", str(exc))

    def _send_email_sync(self, market: MarketRecord, match: MatchResult) -> None:
        assert self.settings.smtp_host
        assert self.settings.smtp_from
        message = EmailMessage()
        message["Subject"] = (
            f"[{match.severity.upper()}] Prediction market reference: {match.organization}"
        )
        message["From"] = self.settings.smtp_from
        message["To"] = ", ".join(self.settings.smtp_to)
        message.set_content(build_plain_text(market, match))

        smtp_class = smtplib.SMTP_SSL if self.settings.smtp_port == 465 else smtplib.SMTP
        with smtp_class(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=30,
        ) as server:
            if self.settings.smtp_use_tls and self.settings.smtp_port != 465:
                server.starttls()
            if self.settings.smtp_username:
                server.login(
                    self.settings.smtp_username,
                    self.settings.smtp_password or "",
                )
            server.send_message(message)
