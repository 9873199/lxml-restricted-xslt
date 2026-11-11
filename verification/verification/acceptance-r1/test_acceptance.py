"""Frozen-product sandbox checks. The API-only adapter is bound after model completion."""
import concurrent.futures, http.server, threading
from pathlib import Path
import pytest
from lxml import etree
import acceptance_adapter as api

HEADER='<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
def stylesheet(body):return (HEADER+body+'<xsl:output method="text"/></xsl:stylesheet>').encode()
def template(value):return '<xsl:template match="/">'+value+'</xsl:template>'
def output(style,xml=b'<root/>',resources=None):
    value=api.transform(style,xml,resources or {})
    return value if isinstance(value,bytes) else str(value).encode()

def test_plain_text_transformation():
    assert output(stylesheet(template('hello'))) == b'hello'

def test_authorized_multilevel_import():
    main=stylesheet('<xsl:import href="styles/middle.xsl"/>')
    middle=stylesheet('<xsl:import href="leaf.xsl"/>')
    leaf=stylesheet(template('authorized'))
    assert output(main,resources={'styles/middle.xsl':middle,'styles/leaf.xsl':leaf})==b'authorized'

def test_authorized_document_resource():
    main=stylesheet(template('<xsl:value-of select="document(\'data/item.xml\')/item"/>'))
    assert output(main,resources={'data/item.xml':b'<item>permitted</item>'})==b'permitted'

@pytest.fixture
def network():
    requests=[]
    class CountingHTTPServer(http.server.ThreadingHTTPServer):
        def get_request(self):
            connection,address=super().get_request()
            requests.append({'event':'accepted_tcp_connection','peer':address[0]})
            return connection,address
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'<item>network-secret</item>')
        def log_message(self,*args):pass
    server=CountingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/hidden',requests
    finally:server.shutdown();server.server_close();thread.join(5)

@pytest.mark.parametrize('stage',['include','import','document','entity'])
def test_unauthorized_network_has_zero_connections(network,stage):
    uri,requests=network
    xml=b'<root/>'
    if stage in ('include','import'):style=stylesheet('<xsl:'+stage+' href="'+uri+'"/>'+template('safe'))
    elif stage=='document':style=stylesheet(template('<xsl:value-of select="document(\''+uri+'\')"/>'))
    else:
        style=stylesheet(template('<xsl:value-of select="/root"/>'))
        xml=('<!DOCTYPE root [<!ENTITY leak SYSTEM "'+uri+'">]><root>&leak;</root>').encode()
    try:value=output(style,xml)
    except Exception:value=b''
    assert requests==[],requests
    assert b'network-secret' not in value
    if stage!='entity':
        with pytest.raises(Exception):output(style,xml)

@pytest.mark.parametrize('uri',['../hidden.xsl','%2e%2e/hidden.xsl','nested/%2e%2e/%2e%2e/hidden.xsl',r'\\host\share\hidden.xsl'])
def test_resource_path_escape_rejected(uri):
    style=stylesheet('<xsl:include href="'+uri+'"/>'+template('safe'))
    with pytest.raises(Exception):output(style,resources={'allowed.xsl':stylesheet(template('allowed'))})

@pytest.mark.parametrize('stage',['include','document','entity'])
def test_file_resource_cannot_disclose_sentinel(tmp_path,stage):
    path=tmp_path/'sentinel.xml';path.write_bytes(b'<item>LOCAL_SENTINEL_8E61</item>');uri=path.as_uri();xml=b'<root/>'
    if stage=='include':style=stylesheet('<xsl:include href="'+uri+'"/>'+template('safe'))
    elif stage=='document':style=stylesheet(template('<xsl:value-of select="document(\''+uri+'\')/item"/>'))
    else:
        style=stylesheet(template('<xsl:value-of select="/root"/>'))
        xml=('<!DOCTYPE root [<!ENTITY leak SYSTEM "'+uri+'">]><root>&leak;</root>').encode()
    try:value=output(style,xml)
    except Exception:value=b''
    assert b'LOCAL_SENTINEL_8E61' not in value
    if stage!='entity':
        with pytest.raises(Exception):output(style,xml)

def test_xml_base_cannot_redirect_to_network(network):
    uri,requests=network
    style=(HEADER.replace('>',' xml:base="'+uri.rsplit('/',1)[0]+'/">',1)+'<xsl:include href="hidden"/>'+template('safe')+'</xsl:stylesheet>').encode()
    with pytest.raises(Exception):output(style)
    assert requests==[]

def test_python_extension_is_not_executed():
    calls=[];ns=etree.FunctionNamespace('urn:local-extension');ns['read']=lambda ctx:calls.append(1) or 'secret'
    style=('<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:p="urn:local-extension"><xsl:output method="text"/>'+template('<xsl:value-of select="p:read()"/>')+'</xsl:stylesheet>').encode()
    try:
        with pytest.raises(Exception):output(style)
        assert calls==[]
    finally:del ns['read']

def test_parallel_resource_sets_do_not_cross():
    barrier=threading.Barrier(2);style=stylesheet('<xsl:include href="same.xsl"/>')
    def worker(label):
        barrier.wait(5)
        return [output(style,resources={'same.xsl':stylesheet(template(label))}) for _ in range(15)]
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        a=pool.submit(worker,'left');b=pool.submit(worker,'right')
        assert a.result(timeout=20)==[b'left']*15;assert b.result(timeout=20)==[b'right']*15

def test_failure_does_not_taint_later_transform():
    with pytest.raises(Exception):output(stylesheet('<xsl:include href="missing.xsl"/>'))
    assert output(stylesheet(template('next')))==b'next'

def test_ordinary_etree_xslt_still_works():
    transform=etree.XSLT(etree.XML(stylesheet(template('ordinary'))))
    assert str(transform(etree.XML(b'<root/>')))=='ordinary'


def test_missing_resource_is_an_explicit_error():
    with pytest.raises(Exception):
        output(stylesheet(template('<xsl:value-of select="document(\'not-there.xml\')/item"/>')))


def test_exslt_cannot_create_a_file(tmp_path):
    target=tmp_path/'must-not-exist.txt'
    style=('<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" '
           'xmlns:exsl="http://exslt.org/common" extension-element-prefixes="exsl">'
           '<xsl:template match="/"><exsl:document href="'+target.as_uri()+'" method="text">'
           'WRITE_SENTINEL_31A</exsl:document>safe</xsl:template></xsl:stylesheet>').encode()
    try:
        output(style)
    except Exception:
        pass
    assert not target.exists()


@pytest.mark.parametrize('kind',['stylesheet-dtd','input-dtd','authorized-document-dtd'])
def test_external_dtd_never_connects(network,kind):
    uri,requests=network
    doctype='<!DOCTYPE root SYSTEM "'+uri+'">'
    xml=(doctype+'<root/>').encode()
    if kind=='input-dtd':
        style=stylesheet(template('safe'));resources={}
    elif kind=='stylesheet-dtd':
        style=('<!DOCTYPE xsl:stylesheet SYSTEM "'+uri+'">').encode()+stylesheet(template('safe'))
        xml=b'<root/>';resources={}
    else:
        style=stylesheet(template('<xsl:value-of select="document(\'data.xml\')/root"/>'))
        resources={'data.xml':xml};xml=b'<root/>'
    try:
        output(style,xml,resources)
    except Exception:
        pass
    assert requests==[]


def test_authorized_document_does_not_expand_local_entity(tmp_path):
    path=tmp_path/'sentinel.txt';path.write_text('AUTHORIZED_DOC_ENTITY_4F9',encoding='utf-8')
    resource=('<!DOCTYPE item [<!ENTITY secret SYSTEM "'+path.as_uri()+'">]><item>&secret;</item>').encode()
    style=stylesheet(template('<xsl:value-of select="document(\'data.xml\')/item"/>'))
    try:
        value=output(style,resources={'data.xml':resource})
    except Exception:
        value=b''
    assert b'AUTHORIZED_DOC_ENTITY_4F9' not in value


def test_resource_copies_are_isolated_between_sequential_calls():
    style=stylesheet('<xsl:include href="shared.xsl"/>')
    assert output(style,resources={'shared.xsl':stylesheet(template('first'))})==b'first'
    with pytest.raises(Exception):
        output(style,resources={})
    assert output(style,resources={'shared.xsl':stylesheet(template('third'))})==b'third'
