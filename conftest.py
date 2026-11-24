def pytest_configure(config):
    # Phase 5: opt-in Besu tests (tests/test_besu.py); they also need QICAS_BESU=1 and a running network.
    config.addinivalue_line("markers", "besu: needs the Besu QBFT network (QICAS_BESU=1, scripts/besu_up.ps1)")
