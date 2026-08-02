from casino import bankroll


def test_default_config():
    cfg = bankroll.default_config()
    assert cfg == {"stakes": "sim", "burn_cap": 20000, "earn_multiplier": 1.0}


def test_no_burn_in_sim_mode():
    cfg = bankroll.default_config()
    assert bankroll.resolve_burn(500, cfg, env={}) == 0


def test_burn_in_real_mode_clamped_to_cap():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    assert bankroll.resolve_burn(500, cfg, env={}) == 500
    assert bankroll.resolve_burn(999999, cfg, env={}) == 20000


def test_kill_switch_env_forces_zero():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    assert bankroll.resolve_burn(500, cfg, env={"CASINO_NO_BURN": "1"}) == 0


def test_kill_switch_empty_value_still_forces_zero():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    assert bankroll.resolve_burn(500, cfg, env={"CASINO_NO_BURN": ""}) == 0


def test_no_burn_on_win_or_push():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    assert bankroll.resolve_burn(0, cfg, env={}) == 0
    assert bankroll.resolve_burn(-100, cfg, env={}) == 0


def test_credit_amount_applies_multiplier_and_floors():
    assert bankroll.credit_amount(1000, {"earn_multiplier": 1.0}) == 1000
    assert bankroll.credit_amount(1000, {"earn_multiplier": 0.5}) == 500
    assert bankroll.credit_amount(3, {"earn_multiplier": 0.5}) == 1  # floored
