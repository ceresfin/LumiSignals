# Migration Guide: Old Files to New Structure

## File Mapping

### Core Lambda Files
- `enhanced_lambda_preserve_orders.py` → Split into:
  - `main.py` (Lambda handler)
  - `sync/active_trades.py` (lines 305-430)
  - `sync/pending_orders.py` (lines 431-567)
  - `sync/exposures.py` (lines 568-719)
  - `sync/positions.py` (lines 720-844)
  - `sync/closed_trades.py` (lines 845-1140)

### Utility Functions
- OANDA API calls → `utils/oanda_api.py`
- Airtable operations → `utils/airtable_api.py`
- Calculations (pips, exposure, etc.) → `utils/calculations.py`

### Configuration
- Field mappings → `config/field_mappings.py`
- Close reason mappings → `config/field_mappings.py`

## Archived/Deprecated Files

The following files in the root directory are now deprecated and their functionality has been consolidated:

### Sync Scripts (replaced by organized modules)
- `sync_live_oanda_to_airtable.py`
- `sync_closed_trades_correct_fields.py`
- `sync_missing_closed_trades.py`
- `sync_actual_closed_trades.py`
- `enhance_closed_trades_sync.py`
- `force_closed_trades_sync.py`
- `populate_position_tables.py`
- `populate_all_missing_data.py`

### Test Scripts (functionality verified and integrated)
- `test_airtable_simple.py`
- `test_closed_trades.py`
- `test_lambda_closed_trades.py`
- `test_exposure_calculations.py`
- `test_positions_api.py`

### Deployment Scripts (simplified in new structure)
- `deploy_enhanced_lambda.py`
- `deploy_lambda_with_*.py` (various versions)

## Key Improvements

1. **Modular Structure**: Each sync operation is now in its own module
2. **Shared Utilities**: Common functions are centralized
3. **Clear Configuration**: All field mappings in one place
4. **Better Testing**: Can test individual sync modules
5. **Easier Deployment**: Single directory to package

## Migration Steps

1. **Stop using root-level sync scripts** - Use the organized modules instead
2. **Update deployment scripts** - Point to `infrastructure/lambda/trade-sync/`
3. **Test the new structure** - Run `python main.py` locally
4. **Deploy to Lambda** - Package the entire `trade-sync` directory

## Breaking Changes

- Import paths have changed (now use module imports)
- Function signatures simplified (credentials passed differently)
- Some utility functions moved to dedicated modules

## Backwards Compatibility

The new structure maintains all functionality from the original files. No data or features have been removed, only reorganized for better maintainability.