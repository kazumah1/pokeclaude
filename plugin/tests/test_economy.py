from casino import economy


def test_tier_from_multiple_boundaries():
    assert economy.tier_from_multiple(190, 100) == "COMMON"      # 1.9
    assert economy.tier_from_multiple(200, 100) == "RARE"        # 2.0
    assert economy.tier_from_multiple(799, 100) == "RARE"        # 7.99
    assert economy.tier_from_multiple(800, 100) == "LEGENDARY"   # 8.0
    assert economy.tier_from_multiple(2999, 100) == "LEGENDARY"  # 29.99
    assert economy.tier_from_multiple(3000, 100) == "MYTHICAL"   # 30.0


def test_tier_from_multiple_zero_stake_is_common():
    # A positive payout with nothing staked is not a "big multiple" achievement.
    assert economy.tier_from_multiple(500, 0) == "COMMON"


def test_price_of_by_species_own_tier():
    from pokeclaude import encounter
    assert economy.price_of(1) == 500        # Bulbasaur, COMMON
    assert economy.price_of(150) == 8000     # Mewtwo, apex -> LEGENDARY-band price
    assert economy.price_of(151) == 25000    # Mew, MYTHICAL
    # price_of matches the PRICE table keyed by the species' own rarity_tier
    assert economy.price_of(1) == economy.PRICE[encounter.rarity_tier(1)]


def test_rare_tier_is_empty_so_fallback_lands_legendary():
    # The real roster has no RARE-band species; RARE must fall back.
    assert economy.ids_in_tier("RARE") == []
    assert economy.resolve_grant_tier("RARE") == "LEGENDARY"


def test_resolve_grant_tier_common_and_populated_tiers():
    assert economy.resolve_grant_tier("COMMON") == "COMMON"
    assert economy.resolve_grant_tier("LEGENDARY") == "LEGENDARY"
    assert economy.resolve_grant_tier("MYTHICAL") == "MYTHICAL"


def test_grant_on_win_records_in_band_species(pokeclaude_home):
    from pokeclaude import store as dex_store, encounter
    granted = economy.grant_on_win(3500, 100)  # mult 35 -> MYTHICAL
    assert granted is not None
    assert granted["tier"] == "MYTHICAL"
    # engine-rolled species is a real MYTHICAL, and it was written to the temp dex
    assert encounter.rarity_tier(granted["id"]) == "MYTHICAL"
    assert granted["id"] in dex_store.caught_ids(path=dex_store.DEX_PATH)


def test_grant_on_win_common_always_grants_exactly_one(pokeclaude_home):
    from pokeclaude import store as dex_store
    before = len(dex_store.caught_ids(path=dex_store.DEX_PATH))
    granted = economy.grant_on_win(100, 100)  # mult 1 -> COMMON
    assert granted["tier"] == "COMMON"
    after = dex_store.load(path=dex_store.DEX_PATH)["totals"]["catches"]
    assert after == 1  # exactly one catch recorded
    assert len(dex_store.caught_ids(path=dex_store.DEX_PATH)) == before + 1


def test_grant_on_win_rare_falls_back_and_still_grants(pokeclaude_home):
    from pokeclaude import store as dex_store, encounter
    granted = economy.grant_on_win(400, 100)  # mult 4 -> RARE -> fallback LEGENDARY
    assert granted["tier"] == "RARE"           # the tier the win earned
    # but the species actually granted is from the fallback band (LEGENDARY)
    assert encounter.rarity_tier(granted["id"]) == "LEGENDARY"
    assert granted["id"] in dex_store.caught_ids(path=dex_store.DEX_PATH)
