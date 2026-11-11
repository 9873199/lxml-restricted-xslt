"""Restricted XSLT transformations.

This module re-exports the restricted XSLT API from :mod:`lxml.etree`.
See ``RestrictedXSLT`` and ``restricted_xslt_transform()`` there.

The restricted entry point only reads the stylesheet and the explicitly
authorized, read-only resources that the caller provides.  It does not read
files, access the network, call Python extension functions, or change
process-wide parser settings.
"""

from lxml.etree import (
    RestrictedResourceError,
    RestrictedXSLT,
    RestrictedXSLTError,
    restricted_xslt_transform,
)

__all__ = [
    'RestrictedResourceError',
    'RestrictedXSLT',
    'RestrictedXSLTError',
    'restricted_xslt_transform',
]
