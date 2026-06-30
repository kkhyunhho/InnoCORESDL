"""The cell layer: device drivers composed behind the ``Cell`` protocol.

- ``cell_protocol`` — the ``Cell`` interface + ``CellError`` hierarchy.
- ``pump_gantry_cell`` — ``PumpGantryCell`` (cell1–3): pump + XZ gantry.
- ``balance_linear_cell`` — ``BalanceLinearCell`` (cell4): balance + linear rail.
- ``fake_cell`` — in-memory ``FakeCell`` for tests / ``--fake`` dev.

Import the concrete classes from their submodules (e.g.
``from cell.pump_gantry_cell import PumpGantryCell``) so a fake-only path
never has to import the real-driver cells.
"""
