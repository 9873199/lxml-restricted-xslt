import unittest
from lxml.tests.common_imports import make_doctest
r=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite([make_doctest('resolvers.txt')]))
raise SystemExit(0 if r.wasSuccessful() else 1)
