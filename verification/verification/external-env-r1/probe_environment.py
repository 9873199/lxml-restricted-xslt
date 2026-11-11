import ctypes,json,sys
from ctypes.util import find_library
from lxml.tests import test_external_document as t
found=find_library('xml2')
try:
    ctypes.CDLL(found)
    outcome='loaded'
except Exception as exc:
    outcome=type(exc).__name__+': '+str(exc)
print(json.dumps({'platform':sys.platform,'find_library_xml2':found,'CDLL_result':outcome,'upstream_test_suite_count':t.test_suite().countTestCases()}))
