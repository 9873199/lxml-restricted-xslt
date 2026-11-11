"""Tests for the restricted XSLT transformation entry point."""

import copy
import gc
import os
import pathlib
import shutil
import socketserver
import tempfile
import threading
import unittest
import weakref

from contextlib import contextmanager

from .common_imports import etree, HelperTestCase


XSL_HEADER = b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'''

XSL_FOOTER = b'</xsl:stylesheet>'


def make_document_stylesheet(uri, prefix=b''):
    if isinstance(uri, str):
        uri = uri.encode('utf-8')
    return XSL_HEADER + prefix + (
        b'  <xsl:template match="/">\n'
        b'    <out><xsl:copy-of select="document(\'' + uri + b'\')/*"/></out>\n'
        b'  </xsl:template>'
    ) + XSL_FOOTER


class _CountingTCPServer(socketserver.TCPServer):
    """A TCP server that counts each accepted connection."""
    allow_reuse_address = True

    def __init__(self, server_address, handler_class):
        self.connection_count = 0
        super().__init__(server_address, handler_class)

    def get_request(self):
        request, address = super().get_request()
        self.connection_count += 1
        return request, address


class _ClosingHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(0.2)
            self.request.recv(4096)
        except OSError:
            pass


class RestrictedXSLTTestCase(HelperTestCase):
    etree = etree

    # -- helpers ---------------------------------------------------------

    def _temp_file(self, data=b'<sentinel>SECRET</sentinel>'):
        handle, filename = tempfile.mkstemp(prefix='lxml-restricted-', suffix='.xml')
        with os.fdopen(handle, 'wb') as f:
            f.write(data)
        self.addCleanup(os.unlink, filename)
        return filename

    @staticmethod
    def _file_url(filename):
        return 'file:///' + filename.replace(os.sep, '/')

    def _assert_denied(self, stylesheet, resources, input_xml=b'<input/>'):
        with self.assertRaises((etree.RestrictedResourceError, etree.XSLTApplyError)):
            etree.RestrictedXSLT(stylesheet, resources)(input_xml)

    @contextmanager
    def _with_counting_server(self, server):
        thread = threading.Thread(
            target=server.serve_forever, kwargs={'poll_interval': 0.05},
            daemon=True)
        thread.start()
        try:
            yield 'http://127.0.0.1:%d/' % server.server_address[1]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    # -- allowed behaviour ----------------------------------------------

    def test_multilevel_import_include_and_text_output(self):
        resources = {
            'main.xsl': b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:import href="parts/first.xsl"/>
  <xsl:template match="/"><out><xsl:call-template name="result"/></out></xsl:template>
</xsl:stylesheet>''',
            'parts/first.xsl': b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:import href="../second.xsl"/>
</xsl:stylesheet>''',
            'second.xsl': b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:include href="parts/third.xsl"/>
</xsl:stylesheet>''',
            'parts/third.xsl': b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template name="result"><xsl:text>multi-level text</xsl:text></xsl:template>
</xsl:stylesheet>''',
        }
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        result = transform(b'<input/>')
        self.assertEqual('multi-level text', ''.join(result.getroot().itertext()))

    def test_relative_document_and_xml_base_inside_root(self):
        resources = {
            'main.xsl': b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template match="/">
    <out><span xml:base="sub/"><xsl:copy-of select="document('data.xml')/*"/></span></out>
  </xsl:template>
</xsl:stylesheet>''',
            'sub/data.xml': b'<data>allowed</data>',
            'data.xml': b'<data>root</data>',
        }
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        result = transform(b'<input/>')
        self.assertEqual('allowed', result.getroot()[0][0].text)

    def test_resource_map_is_snapshotted(self):
        resources = {
            'main.xsl': make_document_stylesheet('data.xml'),
            'data.xml': b'<data>original</data>',
        }
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        resources['data.xml'] = b'<data>changed</data>'
        self.assertEqual('original', transform(b'<input/>').getroot()[0].text)

    def test_copy_and_deepcopy(self):
        resources = {'main.xsl': make_document_stylesheet('data.xml'),
                     'data.xml': b'<data>copy</data>'}
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        for copied in (copy.copy(transform), copy.deepcopy(transform)):
            self.assertEqual('copy', copied(b'<input/>').getroot()[0].text)

    def test_pathlike_resources_are_snapshotted(self):
        directory = tempfile.mkdtemp(prefix='lxml-restricted-')
        self.addCleanup(shutil.rmtree, directory)
        stylesheet_path = pathlib.Path(directory) / 'main.xsl'
        data_path = pathlib.Path(directory) / 'data.xml'
        stylesheet_path.write_bytes(make_document_stylesheet('data.xml'))
        data_path.write_bytes(b'<data>first</data>')

        transform = etree.RestrictedXSLT(
            stylesheet_path, {pathlib.Path('data.xml'): data_path})
        data_path.write_bytes(b'<data>second</data>')
        self.assertEqual('first', transform(b'<input/>').getroot()[0].text)

    # -- rejections ------------------------------------------------------

    def test_unlisted_relative_resource_is_rejected(self):
        stylesheet = make_document_stylesheet('missing.xml')
        self._assert_denied(stylesheet, {})

    def test_unlisted_include_is_rejected(self):
        stylesheet = XSL_HEADER + b'''
  <xsl:include href="missing.xsl"/>
  <xsl:template match="/"><out/></xsl:template>''' + XSL_FOOTER
        with self.assertRaises(etree.RestrictedResourceError):
            etree.RestrictedXSLT(stylesheet, {})

    def test_file_uri_not_read(self):
        sentinel = self._temp_file(b'<secret>DO NOT READ</secret>')
        stylesheet = make_document_stylesheet(self._file_url(sentinel))
        with self.assertRaises(etree.RestrictedResourceError) as context:
            etree.RestrictedXSLT(stylesheet, {})(b'<input/>')
        self.assertNotIn('DO NOT READ', str(context.exception))

    def test_existing_relative_file_is_not_read(self):
        # A file with the requested relative name exists in the working
        # directory, but only the virtual resource root is consulted.
        filename = 'lxml-restricted-sentinel-%d.xml' % os.getpid()
        path = os.path.join(os.getcwd(), filename)
        with open(path, 'wb') as f:
            f.write(b'<this is not well-formed')
        self.addCleanup(os.unlink, path)
        stylesheet = make_document_stylesheet(filename)
        with self.assertRaises(etree.RestrictedResourceError):
            etree.RestrictedXSLT(stylesheet, {})(b'<input/>')

    def test_input_external_entities_are_rejected(self):
        sentinel = self._temp_file()
        url = self._file_url(sentinel)
        stylesheet = XSL_HEADER + b'''
  <xsl:template match="/"><out/></xsl:template>''' + XSL_FOOTER
        xml = ('<!DOCTYPE root SYSTEM "%s"><root/>' % url).encode()
        with self.assertRaises(etree.RestrictedResourceError):
            etree.RestrictedXSLT(stylesheet, {})(xml)

        xml = ('<!DOCTYPE root [<!ENTITY secret SYSTEM "%s">]>'
               '<root>&secret;</root>' % url).encode()
        with self.assertRaises(etree.RestrictedResourceError):
            etree.RestrictedXSLT(stylesheet, {})(xml)

    def test_path_forms_cannot_escape(self):
        sentinel = self._temp_file()
        cases = {
            'parent': '../../outside.xml',
            'absolute': '/etc/passwd',
            'file': self._file_url(sentinel),
            'encoded': '%2e%2e%2foutside.xml',
            'unc': r'\\server\share\x.xml',
            'windows': r'C:\windows\x.xml',
            'nested-parent': 'sub/../../outside.xml',
        }
        for name, uri in cases.items():
            with self.subTest(path=name):
                self._assert_denied(make_document_stylesheet(uri), {})

    def test_stylesheet_xml_base_cannot_escape(self):
        stylesheet = XSL_HEADER + b'''
  <xsl:template match="/">
    <out><span xml:base="file:///etc/"><xsl:copy-of select="document('passwd')/*"/></span></out>
  </xsl:template>''' + XSL_FOOTER
        self._assert_denied(stylesheet, {})

        stylesheet = XSL_HEADER + b'''
  <xsl:template match="/">
    <out><span xml:base="../../outside/"><xsl:copy-of select="document('data.xml')/*"/></span></out>
  </xsl:template>''' + XSL_FOOTER
        self._assert_denied(stylesheet, {})

    def test_invalid_resource_names(self):
        for name in ('../outside.xml', '/absolute.xml', 'file:///x.xml',
                     r'\\server\share\x.xml', r'C:\windows\x.xml',
                     'sub/%2e%2e/x.xml', '', ' x.xml'):
            with self.subTest(name=name):
                with self.assertRaises((TypeError, ValueError)):
                    etree.RestrictedXSLT(XSL_HEADER + XSL_FOOTER, {name: b'<x/>'})

    # -- no network / no default loader --------------------------------

    def test_http_document_makes_no_connection(self):
        server = _CountingTCPServer(('127.0.0.1', 0), _ClosingHandler)
        with self._with_counting_server(server) as base_url:
            stylesheet = make_document_stylesheet(base_url + 'resource.xml')
            with self.assertRaises(etree.RestrictedResourceError):
                etree.RestrictedXSLT(stylesheet, {})(b'<input/>')
        self.assertEqual(0, server.connection_count)

    def test_http_external_entity_makes_no_connection(self):
        server = _CountingTCPServer(('127.0.0.1', 0), _ClosingHandler)
        with self._with_counting_server(server) as base_url:
            stylesheet = XSL_HEADER + b'''
  <xsl:template match="/"><out/></xsl:template>''' + XSL_FOOTER
            xml = ('<!DOCTYPE root SYSTEM "%sentity.dtd"><root/>' % base_url).encode()
            with self.assertRaises(etree.RestrictedResourceError):
                etree.RestrictedXSLT(stylesheet, {})(xml)
        self.assertEqual(0, server.connection_count)

    # -- extension functions / global state ----------------------------

    def test_python_extension_functions_are_not_exposed(self):
        namespace = 'http://lxml.example/restricted-extension-test'
        etree.FunctionNamespace(namespace)['upper'] = \
            lambda context, value: value.upper()

        stylesheet = b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:ext="http://lxml.example/restricted-extension-test">
  <xsl:template match="/">
    <out><xsl:value-of select="ext:upper('abc')"/></out>
  </xsl:template>
</xsl:stylesheet>'''

        # Unrestricted XSLT still calls the Python function.
        unrestricted = etree.XSLT(etree.XML(stylesheet))
        self.assertEqual('ABC', unrestricted(etree.XML(b'<input/>')).getroot().text)

        # The restricted entry point does not register it.
        with self.assertRaises(etree.XSLTError):
            etree.RestrictedXSLT(stylesheet, {})(b'<input/>')

    def test_regexp_extensions_are_disabled(self):
        stylesheet = b'''\
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:re="http://exslt.org/regular-expressions">
  <xsl:template match="/">
    <out><xsl:value-of select="re:replace('abc', 'b', 'X')"/></out>
  </xsl:template>
</xsl:stylesheet>'''
        with self.assertRaises(etree.XSLTError):
            etree.RestrictedXSLT(stylesheet, {})(b'<input/>')

    def test_extension_argument_is_not_supported(self):
        transform = etree.RestrictedXSLT
        with self.assertRaises(TypeError):
            transform(XSL_HEADER + XSL_FOOTER, {}, extensions={})

    def test_global_default_parser_is_unchanged(self):
        parser = etree.get_default_parser()
        resolvers = repr(parser.resolvers)
        etree.RestrictedXSLT(XSL_HEADER + XSL_FOOTER, {})(b'<input/>')
        self.assertIs(parser, etree.get_default_parser())
        self.assertEqual(resolvers, repr(parser.resolvers))

    # -- lifecycle and threading ---------------------------------------

    def test_reuse_after_failed_transformation(self):
        resources = {
            'main.xsl': XSL_HEADER + b'''
  <xsl:param name="href"/>
  <xsl:template match="/">
    <out><xsl:copy-of select="document($href)/*"/></out>
  </xsl:template>''' + XSL_FOOTER,
            'present.xml': b'<data>present</data>',
        }
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        with self.assertRaises(etree.RestrictedResourceError):
            transform(b'<input/>', href=etree.XSLT.strparam('missing.xml'))

        # The stored resolver error of the failed run must not leak into the
        # next run of the same transform object.
        result = transform(b'<input/>', href=etree.XSLT.strparam('present.xml'))
        self.assertEqual('present', result.getroot()[0].text)

    def test_transform_releases_state_on_destruction(self):
        resources = {'main.xsl': make_document_stylesheet('data.xml'),
                     'data.xml': b'<data>value</data>'}
        transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
        ref = weakref.ref(transform)
        del transform
        gc.collect()
        self.assertIsNone(ref())

    def test_thread_isolation_with_same_resource_names(self):
        results = {}
        errors = []

        def worker(index):
            resources = {
                'main.xsl': make_document_stylesheet('data.xml'),
                'data.xml': ('<data>value-%d</data>' % index).encode(),
            }
            try:
                transform = etree.RestrictedXSLT(resources['main.xsl'], resources)
                for _ in range(20):
                    result = transform(b'<input/>')
                    results[index] = result.getroot()[0].text
            except Exception as exc:  # pragma: no cover - debugging aid
                errors.append((index, exc))

        threads = [threading.Thread(target=worker, args=(index,))
                   for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        for index in range(8):
            self.assertEqual('value-%d' % index, results.get(index))


def test_suite():
    return unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedXSLTTestCase)


if __name__ == '__main__':
    print('to test use test.py %s' % __file__)
