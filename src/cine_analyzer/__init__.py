"""Automated Cinematography Analyzer.

Importing this package performs no I/O, reads no environment variable, mutates
no environment, configures no logging, and loads no model. Every side effect is
behind an explicit call: :func:`cine_analyzer.settings.load_settings` reads the
environment, :func:`cine_analyzer.logging_setup.configure_logging` installs the
log configuration.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
