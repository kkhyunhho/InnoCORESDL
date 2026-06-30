# Root conftest: its presence puts the SyringeLiquidHandler root dir on
# sys.path, so the top-level packages import in tests without packaging —
# the tests use `cell.fake_cell` and `server` (which pull in `vendor`, …).
