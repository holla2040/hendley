"""PCBWay provider — the anti-coupling proof (architecture risk 20.5).

Deliberately scoped for v1: PCBWay has no public parts/stock API comparable
to JLC's, so there is **no PCBWay DataSource** — no scraping, no invented
inventory. The strategy resolves lines to ``(mpn, manufacturer)`` identities
(from the knowledge base or exact-part lines) with facts honestly marked
``unverified``; the adapter emits PCBWay's MPN-based BOM template. No CPL.
"""
