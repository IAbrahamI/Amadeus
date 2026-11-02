#!/usr/bin/env python3
"""Start Amadeus Core: python3 run.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amadeus_core.server import main

main()
