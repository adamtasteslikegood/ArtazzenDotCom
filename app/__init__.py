"""Artazzen application package.

Modules are layered: config -> sidecars -> ai_metadata -> watcher ->
security/routes -> factory. Cross-module calls go through module attributes
(e.g. ``config.IMAGES_DIR``) so tests can monkeypatch a single location.
"""
