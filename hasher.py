import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from clcache.pehash import main
main(sys.argv[1:])
