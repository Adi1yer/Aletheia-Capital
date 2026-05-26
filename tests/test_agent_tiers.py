"""Tests for agent tier resolution."""

from datetime import date

from src.agents.tiers import load_tier_config, resolve_active_agent_keys, skipped_agent_keys


def test_load_tier_config_has_core_and_extended():
    cfg = load_tier_config()
    assert len(cfg["core"]) == 8
    assert len(cfg["extended"]) == 14
    assert cfg["extended_rotation_weeks"] == 2


def test_tiered_includes_all_core():
    cfg = load_tier_config()
    active = resolve_active_agent_keys(
        tier_mode="tiered",
        reference_date=date(2026, 1, 5),
        registered_keys=cfg["core"] + cfg["extended"],
    )
    for k in cfg["core"]:
        assert k in active


def test_tiered_rotates_extended():
    cfg = load_tier_config()
    reg = cfg["core"] + cfg["extended"]
    w0 = resolve_active_agent_keys(tier_mode="tiered", reference_date=date(2026, 1, 5), registered_keys=reg)
    w1 = resolve_active_agent_keys(tier_mode="tiered", reference_date=date(2026, 1, 12), registered_keys=reg)
    ext0 = [k for k in w0 if k in cfg["extended"]]
    ext1 = [k for k in w1 if k in cfg["extended"]]
    assert len(ext0) == 7
    assert len(ext1) == 7
    assert set(ext0) != set(ext1)


def test_full_mode_all_registered():
    reg = ["a", "b", "c"]
    assert resolve_active_agent_keys(tier_mode="full", registered_keys=reg) == reg


def test_override_agents():
    active = resolve_active_agent_keys(
        tier_mode="tiered",
        override=["warren_buffett", "cathie_wood"],
        registered_keys=["warren_buffett", "cathie_wood", "ben_graham"],
    )
    assert active == ["warren_buffett", "cathie_wood"]


def test_skipped_agent_keys():
    reg = ["a", "b", "c"]
    assert skipped_agent_keys(reg, ["a", "c"]) == ["b"]
