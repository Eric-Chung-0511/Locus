"""
Rule engine (L2 layer): decide which reviews, inspections and permits apply,
and insert them into the network.

Design idea
    The plant file describes WHAT is being built (assets with attributes).
    The rule pack describes WHAT THE JURISDICTION REQUIRES for such assets.
    Templates describe HOW a requirement changes the network.
    Changing country or owner type means swapping the rule pack, not the code.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from . import distributions as dist
from .model import Model, ModelError, Node, RegisterRow

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ matching
def rule_applies(conditions: dict, asset: dict) -> bool:
    """
    Evaluate `applies_if`:
        key: value        -> asset[key] == value
        key_gte: number   -> asset[key] >= number
        key_lte: number   -> asset[key] <= number
    Missing attributes mean the rule does not apply.
    """
    for key, expected in (conditions or {}).items():
        if key.endswith("_gte"):
            attr = key[:-4]
            if attr not in asset or float(asset[attr]) < float(expected):
                return False
        elif key.endswith("_lte"):
            attr = key[:-4]
            if attr not in asset or float(asset[attr]) > float(expected):
                return False
        else:
            if asset.get(key) != expected:
                return False
    return True


def _require(asset: dict, key: str, rule_id: str) -> Any:
    if key not in asset:
        raise ModelError(f"Rule {rule_id} needs asset '{asset.get('id')}' to define '{key}'")
    return asset[key]


def _review_node(nid: str, name: str, short_name: str, spec: dict, rule: dict, group: str,
                 earliest_day: float = 0.0) -> Node:
    dist.validate(spec, f"rule {rule['id']} node {nid}")
    return Node(
        id=nid, name=name, short_name=short_name, group=group, kind="activity", condition="regulatory",
        duration=dict(spec), earliest_day=earliest_day,
        source_grade=f"{rule.get('process_grade', '-')}/{rule.get('duration_grade', '-')}",
        source_note=f"{rule['legal_basis']}. {rule.get('note', '')}".strip(),
        rule_id=rule["id"],
    )


# ---------------------------------------------------------------- templates
def _t_crane_inspection(model: Model, asset: dict, rule: dict) -> list[str]:
    """
    install -> [document preparation] -> [completion inspection] -> equipment that needs the crane

    Hard part  : the application can only be filed after installation (regulatory FS).
    Soft part  : documents can be prepared during installation (resource link, relaxable).
    """
    rid, aid = rule["id"], asset["id"]
    install = _require(asset, "install_activity", rid)
    feeds = _require(asset, "feeds", rid)
    group = asset.get("group", "Reviews and permits")
    p = rule.get("params", {})

    short = _require(asset, "short_name", rid)
    docs_id, insp_id = f"{aid}_DOCS", f"{aid}_INSPECTION"
    model.add_node(_review_node(docs_id, f"{asset['name']}: inspection documents prepared",
                                f"{short}: inspection papers", p["doc_prep"], rule, group))
    model.add_node(_review_node(insp_id, f"{asset['name']}: completion inspection and load test",
                                f"{short}: inspection", p["inspection"], rule, group))

    model.add_link(install, docs_id, "FS", 0, "resource",
                   "Documents are usually compiled once installation is done",
                   relax={"rel": "SS", "lag": 0,
                          "proposal": "Prepare crane papers during install",
                          "cost": "Compile the application package during installation; small risk of rework if as-built details change"},
                   origin=f"rule:{rid}")
    model.add_link(install, insp_id, "FS", 0, "regulatory",
                   "Application is filed only after installation is complete", origin=f"rule:{rid}")
    model.add_link(docs_id, insp_id, "FS", 0, "regulatory",
                   "Inspection needs a complete application", origin=f"rule:{rid}")

    alt = asset.get("alt_means") or {}
    for target in feeds:
        relax = None
        if alt.get("target") == target:
            relax = {"pred": alt["pred"], "rel": alt.get("rel", "FS"),
                     "lag": alt.get("lag", 0), "proposal": alt.get("proposal", ""),
                     "cost": alt.get("cost", "")}
        model.add_link(insp_id, target, "FS", 0, "means",
                       "Lifting capacity must be available (the certified crane is one means)",
                       relax=relax, origin=f"rule:{rid}")
    return [docs_id, insp_id]


def _t_hv_test_reports(model: Model, asset: dict, rule: dict) -> list[str]:
    """Test reports submitted on a planned day, accepted after review, before energisation."""
    rid, aid = rule["id"], asset["id"]
    group = asset.get("group", "Gate 0: power receipt")
    nid = f"{aid}_TEST_REPORTS"
    model.add_node(_review_node(nid, f"{asset['name']}: equipment test reports accepted",
                                f"{_require(asset, 'short_name', rid)}: test reports accepted",
                                rule["params"]["review"], rule, group,
                                earliest_day=float(_require(asset, "report_submit_day", rid))))
    model.add_link(nid, f"{aid}_ENERGISATION", "FS", 0, "regulatory",
                   "Reports must be accepted before power is delivered", origin=f"rule:{rid}")
    return [nid]


def _t_hv_completion_test(model: Model, asset: dict, rule: dict) -> list[str]:
    rid, aid = rule["id"], asset["id"]
    group = asset.get("group", "Gate 0: power receipt")
    nid = f"{aid}_COMPLETION_TEST"
    model.add_node(_review_node(nid, f"{asset['name']}: completion test",
                                f"{_require(asset, 'short_name', rid)}: completion test",
                                rule["params"]["test"], rule, group))
    model.add_link(_require(asset, "site_test_activity", rid), nid, "FS", 0, "physical",
                   "Completion test runs on installed, site-tested equipment", origin=f"rule:{rid}")
    return [nid]


def _t_grid_energisation(model: Model, asset: dict, rule: dict) -> list[str]:
    """
    completion test -> operation-sequence notice (fixed notice period) -> energisation -> power feeding
    """
    rid, aid = rule["id"], asset["id"]
    group = asset.get("group", "Gate 0: power receipt")
    p = rule["params"]
    short = _require(asset, "short_name", rid)
    notice_id, energ_id, feed_id = f"{aid}_OPS_NOTICE", f"{aid}_ENERGISATION", f"{aid}_POWER_FEED"

    model.add_node(_review_node(notice_id, f"{asset['name']}: operation-sequence notice period",
                                f"{short}: sequence notice",
                                {"dist": "fixed", "value": float(p["notice_days"])}, rule, group))
    model.add_node(_review_node(energ_id, f"{asset['name']}: energisation",
                                f"{short}: energisation", p["energisation"], rule, group))
    model.add_node(_review_node(feed_id, f"{asset['name']}: power feeding",
                                f"{short}: power feeding", p["power_feed"], rule, group))

    model.add_link(f"{aid}_COMPLETION_TEST", notice_id, "FS", 0, "resource",
                   "Sequence sheet is usually submitted after completion tests",
                   relax={"rel": "SS", "lag": 0,
                          "proposal": "Submit the sequence sheet during tests",
                          "cost": "Draft and submit the sequence sheet while tests run; resubmit if results change the sequence"},
                   origin=f"rule:{rid}")
    model.add_link(notice_id, energ_id, "FS", 0, "regulatory",
                   "Dispatch needs the notice period before connection", origin=f"rule:{rid}")
    model.add_link(f"{aid}_COMPLETION_TEST", energ_id, "FS", 0, "regulatory",
                   "Energise only tested equipment", origin=f"rule:{rid}")
    model.add_link(_require(asset, "grid_ready_event", rid), energ_id, "FS", 0, "contractual",
                   "Grid side must be ready", origin=f"rule:{rid}")
    model.add_link(energ_id, feed_id, "FS", 0, "physical",
                   "Power feeding follows successful energisation", origin=f"rule:{rid}")
    for target in asset.get("downstream", []):
        model.add_link(feed_id, target, "FS", 0, "physical",
                       "Plant distribution needs incoming power", origin=f"rule:{rid}")
    return [notice_id, energ_id, feed_id]


def _t_air_permit(model: Model, asset: dict, rule: dict) -> list[str]:
    rid, aid = rule["id"], asset["id"]
    group = asset.get("group", "Reviews and permits")
    nid = f"{aid}_AIR_PERMIT"
    model.add_node(_review_node(nid, f"{asset['name']}: air permit review and test-run notice",
                                f"{_require(asset, 'short_name', rid)}: air permit",
                                rule["params"]["review"], rule, group,
                                earliest_day=float(_require(asset, "submission_day", rid))))
    model.add_link(nid, _require(asset, "first_emission_milestone", rid), "FS", 0, "regulatory",
                   "First fire starts the permitted test run", origin=f"rule:{rid}")
    return [nid]


TEMPLATES: dict[str, Callable[[Model, dict, dict], list[str]]] = {
    "crane_inspection": _t_crane_inspection,
    "hv_test_reports": _t_hv_test_reports,
    "hv_completion_test": _t_hv_completion_test,
    "grid_energisation": _t_grid_energisation,
    "air_permit": _t_air_permit,
}


# ------------------------------------------------------------------- driver
def apply_rule_pack(model: Model, assets: list[dict], pack: dict) -> None:
    """Match every asset against every rule; verified rules change the network,
    pending rules are only listed in the register."""
    model.jurisdiction = pack.get("jurisdiction", "")
    owner_plant = model.meta.get("owner_type")
    owner_pack = pack.get("owner_type")
    if owner_plant and owner_pack and owner_plant != owner_pack:
        logger.warning("Rule pack is written for owner type '%s' but the plant is '%s'",
                       owner_pack, owner_plant)

    rules = pack.get("rules", []) or []
    for rule in rules:
        for key in ("id", "name", "status", "legal_basis", "template"):
            if key not in rule:
                raise ModelError(f"Rule {rule.get('id', '?')} is missing '{key}'")

    for asset in assets:
        if "id" not in asset or "type" not in asset:
            raise ModelError(f"Asset needs 'id' and 'type': {asset}")
        for rule in rules:
            if not rule_applies(rule.get("applies_if", {}), asset):
                continue
            gate_nodes: list[str] = []
            if rule["status"] == "verified":
                template = TEMPLATES.get(rule["template"])
                if template is None:
                    raise ModelError(f"Rule {rule['id']}: unknown template '{rule['template']}'")
                gate_nodes = template(model, asset, rule)
            model.register.append(RegisterRow(
                rule_id=rule["id"], rule_name=rule["name"], status=rule["status"],
                legal_basis=rule["legal_basis"], asset_id=asset["id"],
                asset_name=asset.get("name", asset["id"]), gate_nodes=gate_nodes,
                process_grade=str(rule.get("process_grade", "-")),
                duration_grade=str(rule.get("duration_grade", "-")),
                note=str(rule.get("note", "")).strip(),
            ))
