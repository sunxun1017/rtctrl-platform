#!/usr/bin/env python3
"""Strict extraction utilities; extracted production text is never rewritten."""
import hashlib
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def function(source, name):
    match = re.search(r"^(?:[A-Za-z_][A-Za-z_0-9 \t*]*[ \t*])?" + name + r"\([^;{}]*?\)\s*\{", source, re.M)
    if not match:
        raise ValueError("missing function " + name)
    start = match.start()
    if source[start:match.end()].lstrip().startswith(name + "("):
        start = source.rfind("\n", 0, start - 1) + 1
    depth = 0
    for index in range(source.index("{", match.start()), len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[start:index + 1]
    raise ValueError("unclosed function " + name)


def replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError("expected one occurrence: " + old[:100])
    return source.replace(old, new, 1)


def declaration(source, kind, name):
    match = re.search(r"^" + kind + r"\s+" + name + r"\s*\{", source, re.M)
    if not match:
        raise ValueError("missing declaration " + name)
    end = source.index("\n};", match.end()) + len("\n};")
    return source[match.start():end]
