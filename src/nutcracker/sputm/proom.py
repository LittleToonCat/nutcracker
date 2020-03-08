#!/usr/bin/env python3

import io
import os

import numpy as np

from nutcracker.codex.codex import decode1
from .room import decode_smap, convert_to_pil_image, decode_he, read_uint16le, read_uint32le, read_strip, parse_strip

def read_room_background(image, width, height, zbuffers):
    if image.tag == 'SMAP':
        return decode_smap(height, width, image.data)
    elif image.tag == 'BOMP':
        with io.BytesIO(image.data) as s:
            # pylint: disable=unused-variable
            unk = read_uint16le(s)
            width = read_uint16le(s)
            height = read_uint16le(s)
            # TODO: check if x,y or y,x
            xpad, ypad = read_uint16le(s), read_uint16le(s)
            im = decode1(width, height, s.read())
        return np.asarray(im, dtype=np.uint8)
    elif image.tag == 'BMAP':
        with io.BytesIO(image.data) as s:
            code = s.read(1)[0]
            palen = code % 10
            if 134 <= code <= 138:
                res = decode_he(s, width * height, palen)
                return np.frombuffer(res, dtype=np.uint8).reshape((height, width))
            elif 144 <= code <= 148:
                # TODO: handle transparency
                # tr = TRANSPARENCY
                res = decode_he(s, width * height, palen)
                return np.frombuffer(res, dtype=np.uint8).reshape((height, width))
            elif code == 150:
                return np.full((height, width), s.read(1)[0], dtype=np.uint8)
    else:
        print(image.tag, image.data)
        # raise ValueError(f'Unknown image codec: {tag}')

def decode_smap_v8(height, width, data):
    _, bstr = next(sputm.read_chunks(data))
    _, wrap = next(sputm.read_chunks(bstr.data))
    with io.BytesIO(wrap.data) as s:
        offs = sputm.untag(s)
        img_off, image = s.tell(), s.read()

    # num_strips = len(offs.data) // 4
    # print(width, height, num_strips)
    if len(offs.data) == 0:
        # assert height == 0 or width == 0
        return None

    # strip_width = width // num_strips
 
    strip_width = 8
    num_strips = width // strip_width

    with io.BytesIO(offs.data) as s:
        offs = [read_uint32le(s) for _ in range(num_strips)]
        index = list(zip(offs, offs[1:] + [len(data)]))

    assert img_off == index[0][0], (img_off, index[0][0])
    assert data[16:32] == wrap.data[:16], (data[16:32], wrap.data[:16])

    strips = (wrap.data[offset:end] for offset, end in index)
    return np.hstack([parse_strip(height, strip_width, data) for data in strips])

def read_room_background_v8(image, width, height, zbuffers):
    if image.tag == 'SMAP':
        # s = sputm.generate_schema(image.data)
        # data = sputm.findpath('BSTR/WRAP', sputm(schema=s).map_chunks(image.data)).data
        # off = int.from_bytes(data[4:8], signed=False, byteorder='little')
        return decode_smap_v8(height, width, image.data)
    elif image.tag == 'BOMP':
        with io.BytesIO(image.data) as s:
            width = read_uint32le(s)
            height = read_uint32le(s)
            im = decode1(width, height, s.read())
        return np.asarray(im, dtype=np.uint8)
    else:
        raise ValueError(f'Unknown image codec: {tag}')


def read_rmhd(data):
    print(data)
    if len(data) == 6:
        # 'Game Version < 7'
        rwidth = int.from_bytes(data[:2], signed=False, byteorder='little')
        rheight = int.from_bytes(data[2:4], signed=False, byteorder='little')
        robjs = int.from_bytes(data[4:], signed=False, byteorder='little')
    elif len(data) == 10:
        # 'Game Version == 7'
        version = int.from_bytes(data[:4], signed=False, byteorder='little')
        rwidth = int.from_bytes(data[4:6], signed=False, byteorder='little')
        rheight = int.from_bytes(data[6:8], signed=False, byteorder='little')
        robjs = int.from_bytes(data[8:], signed=False, byteorder='little')
    else:
        # 'Game Version == 8'
        assert len(data) == 24
        version = int.from_bytes(data[:4], signed=False, byteorder='little')
        rwidth = int.from_bytes(data[4:8], signed=False, byteorder='little')
        rheight = int.from_bytes(data[8:12], signed=False, byteorder='little')
        robjs = int.from_bytes(data[12:16], signed=False, byteorder='little')
        zbuffers = int.from_bytes(data[16:20], signed=False, byteorder='little')
        transparency = int.from_bytes(data[20:24], signed=False, byteorder='little')
    return rwidth, rheight, robjs

def read_room(lflf):
    room = sputm.find('ROOM', lflf) or sputm.find('RMDA', lflf)
    rwidth, rheight, _ = read_rmhd(sputm.find('RMHD', room).data)
    # trns = sputm.find('TRNS', room).data  # pylint: disable=unused-variable
    palette = (sputm.find('CLUT', room) or sputm.findpath('PALS/WRAP/APAL', room)).data

    rmim = sputm.find('RMIM', room) or sputm.find('RMIM', lflf)
    rmih = sputm.find('RMIH', rmim)
    if rmih:
        # 'Game Version < 7'
        assert len(rmih.data) == 2
        zbuffers = 1 + int.from_bytes(rmih.data, signed=False, byteorder='little')
        assert 1 <= zbuffers <= 8

        imxx = sputm.find('IM00', rmim)
        im = convert_to_pil_image(
            read_room_background(imxx.children[0], rwidth, rheight, zbuffers)
        )
        zpxx = list(sputm.findall('ZP{:02x}', imxx))
        assert len(zpxx) == zbuffers - 1
        im.putpalette(palette)
        return im

    else:
        # TODO: check for multiple IMAG in room bg (different image state)
        imag = sputm.findpath('IMAG/WRAP', room)
        print(rwidth, rheight)
        bgim = read_room_background_v8(imag.children[1], rwidth, rheight, 0)
        if bgim is None:
            return None
        im = convert_to_pil_image(bgim)
        im.putpalette(palette)
        return im

def read_imhd(data):
    # pylint: disable=unused-variable
    with io.BytesIO(data) as stream:
        obj_id = read_uint16le(stream)
        obj_num_imnn = read_uint16le(stream)
        # should be per imnn, but at least 1
        obj_nums_zpnn = read_uint16le(stream)
        obj_flags = stream.read(1)[0]
        obj_unknown = stream.read(1)[0]
        obj_x = read_uint16le(stream)
        obj_y = read_uint16le(stream)
        obj_width = read_uint16le(stream)
        obj_height = read_uint16le(stream)
        obj_hotspots = stream.read()
        if obj_hotspots:
            # TODO: read hotspots
            pass
        return obj_id, obj_height, obj_width

def read_objects(lflf):
    room = sputm.find('ROOM', lflf) or sputm.find('RMDA', lflf)
    # trns = sputm.find('TRNS', room).data  # pylint: disable=unused-variable
    palette = (sputm.find('CLUT', room) or sputm.findpath('PALS/WRAP/APAL', room)).data

    for obim in sputm.findall('OBIM', room):
        obj_id, obj_height, obj_width = read_imhd(sputm.find('IMHD', obim).data)

        for imxx in sputm.findall('IM{:02x}', obim):
            im = convert_to_pil_image(
                read_room_background(imxx.children[0], obj_width, obj_height, 0)
            )
            im.putpalette(palette)
            yield obj_id, imxx.tag, im

if __name__ == '__main__':
    import argparse
    import pprint

    from .preset import sputm

    parser = argparse.ArgumentParser(description='read smush file')
    parser.add_argument('filename', help='filename to read from')
    args = parser.parse_args()

    with open(args.filename, 'rb') as res:
        root = sputm.find('LECF', sputm.map_chunks(res.read()))
        assert root
        for idx, lflf in enumerate(sputm.findall('LFLF', root)):
            room_bg = read_room(lflf)
            if room_bg is not None:
                room_bg.save(f'LFLF_{1 + idx:04d}_ROOM_RMIM.png')

            for obj_idx, tag, im in read_objects(lflf):
                im.save(f'LFLF_{1 + idx:04d}_ROOM_OBIM_{obj_idx:04d}_{tag}.png')

            # for lflf in sputm.findall('LFLF', t):
            #     tree = sputm.findpath('ROOM/OBIM/IM{:02x}', lflf)
            #     sputm.render(tree)

        print('==========')
