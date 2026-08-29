"""
Scan or migrate saved traceability rules whose ``transformNode`` instances use a
``transform_type`` outside the supported whitelist (plan_69).

The script has two modes:

* **scan** (default, read-only) — produce a blast-radius report.
* **rewrite** — opt-in migration that rewrites every offending value to
  ``passthrough``, records the previous value in node metadata for audit, and
  bumps ``updated_at``. Use this before enforcing the transform contract on a
  production database.

Usage:
    cd backend
    # blast-radius report (read-only)
    python scripts/scan_legacy_transform_types.py

    # migrate offending values to passthrough (writes the database)
    python scripts/scan_legacy_transform_types.py --rewrite-to-passthrough

    # preview the migration plan without writing
    python scripts/scan_legacy_transform_types.py --rewrite-to-passthrough --dry-run

The script is intentionally idempotent: re-running ``--rewrite-to-passthrough``
after a successful run reports zero findings.
"""

import argparse
import asyncio
import copy
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.traceability_rule import TraceabilityRule  # noqa: E402
from app.services.traceability.engine.nodes.transform_node import (  # noqa: E402
    DEFAULT_TRANSFORM_TYPE,
    SUPPORTED_TRANSFORM_TYPES,
    is_supported_transform_type,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scan_legacy_transform_types")


def _coerce_flow(raw_flow: Any) -> Tuple[Dict[str, Any], bool]:
    """Return (flow_dict, was_string).

    ``was_string`` records whether ``flow_json`` is currently stored as a JSON
    string so the caller can re-serialize when writing back.
    """
    if isinstance(raw_flow, str):
        try:
            return json.loads(raw_flow), True
        except json.JSONDecodeError:
            return {}, True
    if isinstance(raw_flow, dict):
        return raw_flow, False
    return {}, False


def _iter_transform_nodes(
    flow: Dict[str, Any],
) -> Iterable[Tuple[int, Dict[str, Any]]]:
    """Yield (index, node_dict) for every ``transformNode`` in the flow."""
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    if not isinstance(nodes, list):
        return
    for index, node in enumerate(nodes):
        if isinstance(node, dict) and node.get("type") == "transformNode":
            yield index, node


def _has_explicit_unsupported_type(node: Dict[str, Any]) -> Tuple[bool, Any]:
    config = (node.get("data") or {}).get("config") or {}
    if "transform_type" not in config:
        return False, None
    value = config.get("transform_type")
    return (not is_supported_transform_type(value)), value


async def _scan_rules(rewrite: bool, dry_run: bool) -> Tuple[int, int]:
    """Return (legacy_count, rewritten_count)."""
    legacy_count = 0
    rewritten_count = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TraceabilityRule))
        rules = result.scalars().all()

        for rule in rules:
            flow, was_string = _coerce_flow(rule.flow_json)
            if not flow:
                continue

            mutated = False
            new_flow = copy.deepcopy(flow) if rewrite else flow

            for index, node in _iter_transform_nodes(new_flow if rewrite else flow):
                is_unsupported, value = _has_explicit_unsupported_type(node)
                if not is_unsupported:
                    continue

                legacy_count += 1
                node_id = str(node.get("id") or "")
                logger.warning(
                    "rule_id=%s name=%r project_id=%s node_id=%s transform_type=%r enabled=%s",
                    rule.id,
                    rule.name,
                    rule.project_id,
                    node_id,
                    value,
                    rule.enabled,
                )

                if rewrite and not dry_run:
                    target = new_flow["nodes"][index]
                    config = target.setdefault("data", {}).setdefault("config", {})
                    config["transform_type"] = DEFAULT_TRANSFORM_TYPE
                    audit = config.setdefault("_legacy_transform_type_audit", {})
                    audit["previous_value"] = value
                    audit["rewritten_at"] = datetime.now(timezone.utc).isoformat()
                    audit["rewritten_by"] = "scripts/scan_legacy_transform_types.py"
                    rewritten_count += 1
                    mutated = True

            if mutated:
                rule.flow_json = json.dumps(new_flow) if was_string else new_flow
                # JSON columns require flag_modified for nested mutations to be
                # picked up by the ORM dirty tracker on dict-backed dialects.
                flag_modified(rule, "flow_json")

        if rewrite and not dry_run and rewritten_count:
            await session.commit()
            logger.info("Committed %d rewrite(s).", rewritten_count)
        elif rewrite and dry_run:
            await session.rollback()

    return legacy_count, rewritten_count


def _print_summary(
    legacy_count: int, rewritten_count: int, *, rewrite: bool, dry_run: bool
) -> None:
    supported = ", ".join(sorted(SUPPORTED_TRANSFORM_TYPES))
    logger.info("Supported transform_types: %s", supported)

    if legacy_count == 0:
        logger.info("No legacy transform_type values detected.")
        return

    if not rewrite:
        logger.warning(
            "Found %d transform node(s) with unsupported transform_type. "
            "Re-run with --rewrite-to-passthrough to migrate.",
            legacy_count,
        )
    elif dry_run:
        logger.warning(
            "DRY RUN: would rewrite %d transform_type value(s) to %r.",
            legacy_count,
            DEFAULT_TRANSFORM_TYPE,
        )
    else:
        logger.warning(
            "Rewrote %d transform_type value(s) to %r.",
            rewritten_count,
            DEFAULT_TRANSFORM_TYPE,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rewrite-to-passthrough",
        action="store_true",
        dest="rewrite",
        help=(
            "Rewrite any unsupported transform_type to passthrough, recording "
            "the previous value under data.config._legacy_transform_type_audit."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what --rewrite-to-passthrough would change, but do not commit.",
    )
    args = parser.parse_args()
    if args.dry_run and not args.rewrite:
        parser.error("--dry-run requires --rewrite-to-passthrough")
    return args


async def _main() -> int:
    args = _parse_args()
    legacy_count, rewritten_count = await _scan_rules(rewrite=args.rewrite, dry_run=args.dry_run)
    _print_summary(
        legacy_count,
        rewritten_count,
        rewrite=args.rewrite,
        dry_run=args.dry_run,
    )
    return 1 if legacy_count > 0 and not (args.rewrite and not args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
