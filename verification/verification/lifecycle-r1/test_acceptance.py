"""Exercise one frozen compiled object, copies, lifetime and unaffected ordinary API."""
import concurrent.futures,copy,gc,threading,tracemalloc
import pytest
from lxml import etree
import acceptance_adapter as api

def style(body):
    return ('<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
            +body+'<xsl:output method="text"/></xsl:stylesheet>').encode()

def text_template(value):return '<xsl:template match="/">'+value+'</xsl:template>'
def render(compiled,xml):return str(compiled(xml))

def test_same_compiled_object_recovers_from_xml_parse_failure():
    compiled=api.compile(style(text_template('<xsl:value-of select="/root/item"/>')), {})
    with pytest.raises(Exception):compiled(b'<root>')
    assert render(compiled,b'<root><item>next</item></root>')=='next'

def document_compiled():
    return api.compile(style(text_template('<xsl:value-of select="document(/root/@uri)/item"/>')),
                       {'allowed.xml':b'<item>authorized</item>'})

def test_same_object_recovers_from_denied_document():
    compiled=document_compiled()
    with pytest.raises(Exception):compiled(b'<root uri="missing.xml"/>')
    assert render(compiled,b'<root uri="allowed.xml"/>')=='authorized'

def test_copy_retains_authorized_resources_after_original_destruction():
    original=document_compiled();cloned=copy.copy(original);del original;gc.collect()
    assert render(cloned,b'<root uri="allowed.xml"/>')=='authorized'
    with pytest.raises(Exception):cloned(b'<root uri="missing.xml"/>')
    assert render(cloned,b'<root uri="allowed.xml"/>')=='authorized'

def test_original_is_not_poisoned_by_failed_then_destroyed_copy():
    original=document_compiled();cloned=copy.copy(original)
    with pytest.raises(Exception):cloned(b'<root uri="missing.xml"/>')
    del cloned;gc.collect()
    assert render(original,b'<root uri="allowed.xml"/>')=='authorized'

def test_precompiled_resource_sets_stay_separate_in_parallel():
    main=style('<xsl:include href="shared.xsl"/>');gate=threading.Barrier(2)
    left=api.compile(main,{'shared.xsl':style(text_template('left'))})
    right=api.compile(main,{'shared.xsl':style(text_template('right'))})
    def run(compiled):
        gate.wait(5);return [render(compiled,b'<root/>') for _ in range(30)]
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        a=pool.submit(run,left);b=pool.submit(run,right)
        assert a.result(timeout=20)==['left']*30
        assert b.result(timeout=20)==['right']*30

def test_restricted_api_leaves_process_default_parser_unchanged():
    original=etree.get_default_parser();compiled=api.compile(style(text_template('plain')), {})
    assert render(compiled,b'<root/>')=='plain'
    assert etree.get_default_parser() is original

def test_global_python_extension_still_works_for_ordinary_xslt():
    calls=[];namespace=etree.FunctionNamespace('urn:ordinary-extension-check')
    namespace['read']=lambda context:calls.append('called') or 'ordinary'
    source=('<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" '
            'xmlns:p="urn:ordinary-extension-check"><xsl:output method="text"/>'
            '<xsl:template match="/"><xsl:value-of select="p:read()"/></xsl:template></xsl:stylesheet>').encode()
    try:
        with pytest.raises(Exception):api.compile(source,{})(b'<root/>')
        assert calls==[]
        ordinary=etree.XSLT(etree.XML(source))
        assert str(ordinary(etree.XML(b'<root/>')))=='ordinary' and calls==['called']
    finally:del namespace['read']

def test_destroyed_instances_do_not_accumulate_resource_payloads():
    main=style(text_template('small'))
    warm=api.compile(main,{});assert render(warm,b'<root/>')=='small';del warm;gc.collect()
    tracemalloc.start()
    try:
        before=tracemalloc.get_traced_memory()[0]
        for _ in range(32):
            resources={'unused.xml':b'<item>'+b'x'*(256*1024)+b'</item>'}
            compiled=api.compile(main,resources);assert render(compiled,b'<root/>')=='small'
            del compiled,resources
        gc.collect();current,peak=tracemalloc.get_traced_memory()
        print({'instances':32,'resource_payload_bytes_each':256*1024,'retained_delta':current-before,'peak_bytes':peak})
        assert current-before<1024*1024,'Destroyed instances retained per-instance resource payloads'
    finally:tracemalloc.stop()
