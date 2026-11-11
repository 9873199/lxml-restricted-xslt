"""Thin mapping of the frozen documented lxml API; no security logic."""
from lxml import etree

def compile(stylesheet, resources):
    return etree.RestrictedXSLT(stylesheet, resources)

def transform(stylesheet, xml, resources):
    return compile(stylesheet, resources)(xml)
