"""
Compatibility shim for legacy tests expecting app.database.
Exports AsyncSessionLocal and init_db by delegating to the current database manager.
"""

