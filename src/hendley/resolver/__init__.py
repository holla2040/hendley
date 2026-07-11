"""The resolver core — provider-independent resolution of Requirements BOMs.

Nothing under this package imports concrete providers or data sources; the
:class:`~hendley.providers.base.ProviderStrategy` and
:class:`~hendley.datasources.base.DataSource` implementations are injected.
"""
