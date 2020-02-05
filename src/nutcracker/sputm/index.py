#!/usr/bin/env python3

import io
import logging
import os
import struct
from typing import Sequence, NamedTuple, Optional, Iterator
from dataclasses import dataclass

from nutcracker.core.stream import StreamView

from .schema import SCHEMA

@dataclass
class Element:
    tag: str
    attribs: dict
    children: Sequence['Element']
    data: StreamView

def findall(tag: str, root: Optional[Element]) -> Iterator[Element]:
    if not root:
        return
    for c in root.children:
        if c.tag == tag:
            yield c

def find(tag: str, root: Optional[Element]) -> Optional[Element]:
    return next(findall(tag, root), None)

def findpath(path: str, root: Optional[Element]) -> Optional[Element]:
    path = os.path.normpath(path)
    if not path or path == '.':
        return root
    dirname, basename = os.path.split(path)
    return find(basename, findpath(dirname, root))

def read_index(data, level=0, base_offset=0):
    chunks = sputm.print_chunks(sputm.read_chunks(data), level=level, base=base_offset)
    for idx, (hoff, (tag, chunk)) in enumerate(chunks):
        if tag == 'DCHR':
            with io.BytesIO(chunk) as s:
                num = int.from_bytes(s.read(2), byteorder='little', signed=False)
                rnums = [int.from_bytes(s.read(1), byteorder='little', signed=False) for i in range(num)]
                offs = [int.from_bytes(s.read(4), byteorder='little', signed=False) for i in range(num)]
                for rnum, off in zip(rnums, offs):
                    print(rnum, off)

def render(element, level=0):
    if not element:
        return
    attribs = ''.join(f' {key}="{value}"' for key, value in element.attribs.items())
    indent = '    ' * level
    closing = '' if element.children else ' /'
    print(f'{indent}<{element.tag}{attribs}{closing}>')
    if element.children:
        for c in element.children:
            render(c, level=level + 1)
        print(f'{indent}</{element.tag}>')

def map_chunks(data, schema=SCHEMA, ptag=None):
    chunks = sputm.read_chunks(data)
    for hoff, (tag, chunk) in chunks:
        if ptag and tag not in schema[ptag]:
            logging.warning('Missing entry for {} in {} schema'.format(tag, ptag))
            exit(1)
        if tag not in schema:
            logging.warning('Missing key in schema: {}'.format(tag))
            exit(1)
        yield Element(
            tag,
            {'offset': hoff, 'size': len(chunk)},
            list(map_chunks(chunk, schema=schema, ptag=tag)) if schema.get(tag) else [],
            chunk
        )

def create_maptree(data):
    return next(map_chunks(data), None)

if __name__ == '__main__':
    import argparse

    from . import sputm

    parser = argparse.ArgumentParser(description='read smush file')
    parser.add_argument('filename', help='filename to read from')
    args = parser.parse_args()

    with open(args.filename, 'rb') as res:
        root = map_chunks(res)
        for t in root:
            render(t)
        # for lflf in findall('LFLF', root):
        #     tree = findpath('RMIM/IM00', lflf)
        #     render(tree)

        # print('==========')