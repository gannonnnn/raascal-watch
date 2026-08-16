from __future__ import annotations

"""Source-aware public exposure and trade snapshots.

The module deliberately distinguishes *visibility* from *evidence*. Polymarket
publishes wallet-level holder and trade data for public markets. Kalshi's public
market endpoints publish aggregate trades without public participant identity.
Neither surface proves who a trader is, why they traded, whether they possessed
nonpublic information, or whether they influenced an outcome.
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from .incentive import polymarket_condition_id, polymarket_outcomes
from .models import MarketRecord


class PublicExposureError(RuntimeError):
    pass


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(value: Any) -> float | None:
    """Normalize either dollar prices (0-1) or legacy cent prices (0-100)."""
    parsed = _float(value)
    if parsed is None:
        return None
    if parsed > 1:
        parsed /= 100.0
    return max(0.0, min(1.0, parsed))


def _iso_from_epoch(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _kalshi_price(dollar_value: Any, cent_value: Any) -> float | None:
    dollars = _float(dollar_value)
    if dollars is not None:
        return dollars
    cents = _float(cent_value)
    if cents is None:
        return None
    return cents / 100.0 if cents > 1 else cents


def _display_name(holder: dict[str, Any], *, require_public_flag: bool = True) -> str:
    wallet = str(holder.get("proxyWallet") or holder.get("wallet") or "").strip()
    may_show_name = (
        not require_public_flag
        or bool(holder.get("displayUsernamePublic", False))
        or bool(holder.get("verified", False))
    )
    if may_show_name:
        for key in ("name", "pseudonym"):
            value = holder.get(key)
            if value and str(value).strip():
                return str(value).strip()
    if len(wallet) > 14:
        return f"{wallet[:7]}…{wallet[-5:]}"
    return wallet or "Public wallet"


def _wallet(holder: dict[str, Any]) -> str:
    return str(holder.get("proxyWallet") or holder.get("wallet") or "").strip()


def _outcome_label(outcomes: list[str], index: int | None, fallback_index: int) -> str:
    resolved = fallback_index if index is None else index
    if 0 <= resolved < len(outcomes):
        return outcomes[resolved]
    return f"Outcome {resolved + 1}"


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any],
) -> Any:
    response = await client.get(url, params=params)
    if response.is_error:
        detail = " ".join(response.text.strip().split())[:500]
        raise PublicExposureError(
            f"HTTP {response.status_code} from public exposure source"
            + (f": {detail}" if detail else "")
        )
    try:
        return response.json()
    except ValueError as exc:
        raise PublicExposureError("Public exposure source returned invalid JSON") from exc


async def _get_list(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any],
) -> list[Any]:
    payload = await _get_json(client, url, params=params)
    if not isinstance(payload, list):
        raise PublicExposureError("Public exposure source returned an unexpected shape")
    return payload


async def _kalshi_trades(
    market: MarketRecord,
    *,
    client: httpx.AsyncClient,
    base_urls: list[str],
    trade_limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    last_error: PublicExposureError | None = None
    for base in dict.fromkeys(item.rstrip("/") for item in base_urls if item):
        endpoint = f"{base}/markets/trades"
        try:
            payload = await _get_json(
                client,
                endpoint,
                params={"ticker": market.external_id, "limit": max(1, min(trade_limit, 100))},
            )
            if not isinstance(payload, dict):
                raise PublicExposureError("Kalshi trade source returned an unexpected shape")
            raw_trades = payload.get("trades")
            if not isinstance(raw_trades, list):
                raw_trades = []
            trades: list[dict[str, Any]] = []
            for item in raw_trades:
                if not isinstance(item, dict):
                    continue
                count = _float(item.get("count_fp") or item.get("count"))
                trades.append(
                    {
                        "trade_id": str(item.get("trade_id") or ""),
                        "wallet": None,
                        "display_name": "Participant not public",
                        "side": None,
                        "outcome": "YES / NO prices",
                        "size": count,
                        "price": _kalshi_price(item.get("yes_price_dollars"), item.get("yes_price")),
                        "yes_price": _kalshi_price(item.get("yes_price_dollars"), item.get("yes_price")),
                        "no_price": _kalshi_price(item.get("no_price_dollars"), item.get("no_price")),
                        "timestamp": str(item.get("created_time") or ""),
                        "transaction_hash": None,
                        "is_block_trade": bool(item.get("is_block_trade", False)),
                    }
                )
            return trades, endpoint
        except PublicExposureError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return [], None


async def fetch_public_exposure(
    market: MarketRecord,
    *,
    client: httpx.AsyncClient,
    polymarket_data_api_url: str,
    kalshi_base_url: str | None = None,
    kalshi_fallback_base_url: str | None = None,
    holder_limit: int = 5,
    trade_limit: int = 12,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    source = market.source.strip().lower()

    if source == "kalshi":
        trades, endpoint = await _kalshi_trades(
            market,
            client=client,
            base_urls=[kalshi_base_url or "", kalshi_fallback_base_url or ""],
            trade_limit=trade_limit,
        )
        return {
            "source": source,
            "captured_at": now,
            "visibility": "aggregate_only",
            "visibility_label": "Aggregate trade visibility only",
            "condition_id": None,
            "open_interest": market.open_interest,
            "position_groups": [],
            "holder_groups": [],
            "recent_trades": trades,
            "source_endpoint": endpoint,
            "detail": (
                "Kalshi's public market-data surface can show prices, volume, open interest, "
                "and executed trades, but it does not publicly attribute positions or gains "
                "to individual customer accounts."
            ),
            "caveat": (
                "Participant-level attribution generally requires the account holder, the "
                "exchange, or an authorized regulator. Aggregate trade timing is a review clue, not proof."
            ),
        }

    if source != "polymarket":
        return {
            "source": source,
            "captured_at": now,
            "visibility": "unknown",
            "visibility_label": "Participant visibility not mapped",
            "condition_id": None,
            "open_interest": market.open_interest,
            "position_groups": [],
            "holder_groups": [],
            "recent_trades": [],
            "source_endpoint": None,
            "detail": "RaaScal Watch has not mapped public participant visibility for this source.",
            "caveat": "Do not infer participant identity or profit from aggregate market data.",
        }

    condition_id = polymarket_condition_id(market.raw or {})
    if not condition_id:
        raise PublicExposureError(
            "This Polymarket record does not contain the condition ID required for holder lookup."
        )

    base = polymarket_data_api_url.rstrip("/")

    # The market-positions endpoint provides the clearest public, wallet-level
    # view of size, average entry price, and P&L. It can be unavailable for some
    # deployments or markets, so holder and trade data remain graceful fallbacks.
    positions_error: str | None = None
    try:
        positions_payload = await _get_list(
            client,
            f"{base}/v1/market-positions",
            params={
                "market": condition_id,
                "status": "ALL",
                "sortBy": "TOTAL_PNL",
                "sortDirection": "DESC",
                "limit": max(1, min(holder_limit, 20)),
                "offset": 0,
            },
        )
    except PublicExposureError as exc:
        positions_payload = []
        positions_error = str(exc)

    holders_error: str | None = None
    try:
        holders_payload = await _get_list(
            client,
            f"{base}/holders",
            params={
                "market": condition_id,
                "limit": max(1, min(holder_limit, 20)),
                "minBalance": 1,
            },
        )
    except PublicExposureError as exc:
        # Keep the snapshot useful when one public analytics endpoint is
        # temporarily unavailable. Positions or trades can still provide a
        # meaningful visibility surface without pretending the missing data
        # was returned.
        holders_payload = []
        holders_error = str(exc)

    open_interest_error: str | None = None
    try:
        oi_payload = await _get_list(client, f"{base}/oi", params={"market": condition_id})
    except PublicExposureError as exc:
        oi_payload = []
        open_interest_error = str(exc)

    trades_error: str | None = None
    try:
        trades_payload = await _get_list(
            client,
            f"{base}/trades",
            params={
                "market": condition_id,
                "limit": max(1, min(trade_limit, 100)),
                "offset": 0,
                "takerOnly": "false",
            },
        )
    except PublicExposureError as exc:
        trades_payload = []
        trades_error = str(exc)

    outcomes = polymarket_outcomes(market.raw or {})
    position_groups: list[dict[str, Any]] = []
    for group_index, group in enumerate(positions_payload):
        if not isinstance(group, dict):
            continue
        positions = group.get("positions")
        if not isinstance(positions, list):
            positions = []
        clean_positions: list[dict[str, Any]] = []
        group_outcome: str | None = None
        for position in positions:
            if not isinstance(position, dict):
                continue
            raw_index = position.get("outcomeIndex")
            try:
                outcome_index = int(raw_index) if raw_index is not None else None
            except (TypeError, ValueError):
                outcome_index = None
            outcome = str(position.get("outcome") or "").strip() or _outcome_label(
                outcomes, outcome_index, group_index
            )
            group_outcome = group_outcome or outcome
            clean_positions.append(
                {
                    "wallet": _wallet(position),
                    "display_name": _display_name(position, require_public_flag=False),
                    "verified_profile": bool(position.get("verified", False)),
                    "asset": str(position.get("asset") or ""),
                    "condition_id": str(position.get("conditionId") or condition_id),
                    "average_price": _float(position.get("avgPrice")),
                    "size": _float(position.get("size")),
                    "current_price": _float(position.get("currPrice")),
                    "current_value": _float(position.get("currentValue")),
                    "cash_pnl": _float(position.get("cashPnl")),
                    "total_bought": _float(position.get("totalBought")),
                    "realized_pnl": _float(position.get("realizedPnl")),
                    "total_pnl": _float(position.get("totalPnl")),
                    "outcome": outcome,
                    "outcome_index": outcome_index,
                }
            )
        position_groups.append(
            {
                "token": str(group.get("token") or ""),
                "outcome": group_outcome or _outcome_label(outcomes, None, group_index),
                "positions": clean_positions,
            }
        )

    holder_groups: list[dict[str, Any]] = []
    for group_index, group in enumerate(holders_payload):
        if not isinstance(group, dict):
            continue
        holders = group.get("holders")
        if not isinstance(holders, list):
            holders = []
        clean_holders: list[dict[str, Any]] = []
        group_outcome: str | None = None
        for holder in holders:
            if not isinstance(holder, dict):
                continue
            raw_index = holder.get("outcomeIndex")
            try:
                outcome_index = int(raw_index) if raw_index is not None else None
            except (TypeError, ValueError):
                outcome_index = None
            outcome = _outcome_label(outcomes, outcome_index, group_index)
            group_outcome = group_outcome or outcome
            amount = _float(holder.get("amount"))
            clean_holders.append(
                {
                    "wallet": _wallet(holder),
                    "display_name": _display_name(holder),
                    "amount": amount,
                    "max_settlement_value": amount,
                    "outcome": outcome,
                    "outcome_index": outcome_index,
                    "display_username_public": bool(holder.get("displayUsernamePublic", False)),
                }
            )
        holder_groups.append(
            {
                "token": str(group.get("token") or ""),
                "outcome": group_outcome or _outcome_label(outcomes, None, group_index),
                "holders": clean_holders,
            }
        )

    open_interest = None
    for item in oi_payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("market") or "").lower() == condition_id.lower():
            open_interest = _float(item.get("value"))
            break

    recent_trades: list[dict[str, Any]] = []
    for item in trades_payload:
        if not isinstance(item, dict):
            continue
        raw_index = item.get("outcomeIndex")
        try:
            outcome_index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError):
            outcome_index = None
        outcome = str(item.get("outcome") or "").strip() or _outcome_label(
            outcomes, outcome_index, 0
        )
        recent_trades.append(
            {
                "trade_id": str(item.get("transactionHash") or ""),
                "wallet": _wallet(item),
                "display_name": _display_name(item),
                "side": str(item.get("side") or "").upper() or None,
                "outcome": outcome,
                "outcome_index": outcome_index,
                "size": _float(item.get("size")),
                "price": _float(item.get("price")),
                "timestamp": _iso_from_epoch(item.get("timestamp")),
                "transaction_hash": str(item.get("transactionHash") or "") or None,
                "is_block_trade": False,
            }
        )
    recent_trades.sort(key=lambda item: item.get("timestamp") or "", reverse=True)

    return {
        "source": source,
        "captured_at": now,
        "visibility": "wallet_level",
        "visibility_label": "Public wallet-level exposure and trade visibility",
        "condition_id": condition_id,
        "open_interest": open_interest,
        "position_groups": position_groups,
        "holder_groups": holder_groups,
        "recent_trades": recent_trades,
        "source_endpoint": base,
        "positions_error": positions_error,
        "holders_error": holders_error,
        "open_interest_error": open_interest_error,
        "trades_error": trades_error,
        "detail": (
            "Polymarket publishes market-scoped positions, top holders, and trades by public "
            "wallet. When available, the position surface includes size, average entry price, "
            "and realized or total P&L, making exposure and timing more observable than on a "
            "private account system."
        ),
        "caveat": (
            "A wallet can be pseudonymous, positions can change before settlement, and a "
            "profitable position does not prove real-world identity, nonpublic access, influence, or misconduct."
        ),
    }
