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


def test_settle_loss_full_shield_when_funded():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    # loss fully covered by bankroll -> no shortfall -> no burn
    bankroll_after, burn = bankroll.settle_loss(300, 10000, cfg, env={})
    assert bankroll_after == 9700
    assert burn == 0


def test_settle_loss_into_the_red_burns_only_shortfall():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    # bet 15000 against a 10000 bankroll and lose: shortfall 5000 burns, bankroll floors at 0
    bankroll_after, burn = bankroll.settle_loss(15000, 10000, cfg, env={})
    assert bankroll_after == 0
    assert burn == 5000


def test_settle_loss_shortfall_is_capped():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    bankroll_after, burn = bankroll.settle_loss(999999, 0, cfg, env={})
    assert bankroll_after == 0
    assert burn == 20000  # clamped to burn_cap


def test_settle_loss_sim_mode_never_burns():
    cfg = bankroll.default_config()  # sim
    bankroll_after, burn = bankroll.settle_loss(15000, 10000, cfg, env={})
    assert bankroll_after == 0
    assert burn == 0


def test_settle_loss_kill_switch_forces_zero_burn():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    bankroll_after, burn = bankroll.settle_loss(15000, 10000, cfg, env={"CASINO_NO_BURN": "1"})
    assert bankroll_after == 0
    assert burn == 0


def test_settle_loss_no_loss_is_noop():
    cfg = {"stakes": "real", "burn_cap": 20000, "earn_multiplier": 1.0}
    assert bankroll.settle_loss(0, 10000, cfg, env={}) == (10000, 0)
