"""Check the frozen public access-control and explicit input integration."""
import copy
import pytest
from lxml import etree

STYLE=b'''<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:output method="text"/><xsl:template match="/"><xsl:value-of select="document('data.xml')/item"/></xsl:template></xsl:stylesheet>'''

def test_access_control_deny_all_blocks_even_authorized_document():
    compiled=etree.RestrictedXSLT(STYLE,{'data.xml':b'<item>allowed</item>'},access_control=etree.XSLTAccessControl.DENY_ALL)
    with pytest.raises(etree.XSLTError):compiled(b'<root/>')

def test_allow_flags_cannot_enable_writes_and_copy_keeps_controls():
    compiled=etree.RestrictedXSLT(STYLE,{'data.xml':b'<item>allowed</item>'},access_control=etree.XSLTAccessControl())
    for subject in (compiled,copy.copy(compiled),copy.deepcopy(compiled)):
        assert str(subject(b'<root/>'))=='allowed'
        assert subject.access_control.options=={'read_file':True,'read_network':True,'write_file':False,'write_network':False,'create_dir':False}

def test_explicit_resource_path_is_a_construction_time_snapshot(tmp_path):
    authorized=tmp_path/'authorized.xml';authorized.write_bytes(b'<item>first</item>')
    compiled=etree.RestrictedXSLT(STYLE,{'data.xml':authorized})
    authorized.unlink()
    assert str(compiled(b'<root/>'))=='first'

def test_input_element_is_reparsed_without_its_attached_resolver():
    calls=[]
    class OriginalResolver(etree.Resolver):
        def resolve(self,url,pubid,context):
            calls.append(url)
            return self.resolve_string('<item>outside</item>',context)
    parser=etree.XMLParser();parser.resolvers.add(OriginalResolver())
    element=etree.fromstring(b'<root/>',parser)
    compiled=etree.RestrictedXSLT(STYLE,{'data.xml':b'<item>private</item>'})
    assert str(compiled(element))=='private' and calls==[]
