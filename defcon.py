#!/usr/bin/env python3
"""Compatibility entry point for the DEFinition CONtainer generator.

Implementation lives in cli, job_parser, tracer, dependency_resolver,
definition_generator, and environments. Existing stage imports remain available.
"""

from cli import main, stage1, stage2
from definition_generator import _shell_quote
from environments import load_env_vars
from job_parser import parse_qsub


if __name__ == "__main__":
    main()
