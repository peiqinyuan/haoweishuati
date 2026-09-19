# -*- coding: utf-8 -*-
"""生成 icon.ico（纯标准库，无依赖）
画：蓝色渐变底 + 白色圆角边框 + 白色对勾
"""
import os
import struct


def draw(size):
    """按归一化坐标绘制像素，返回 RGBA 列表（自上而下）"""
    px = []
    cx, cy = 0.5, 0.5
    for y in range(size):
        for x in range(size):
            nx, ny = (x + 0.5) / size, (y + 0.5) / size
            # 蓝底渐变
            r = int(37 + 40 * (1 - ny))
            g = int(99 + 40 * (1 - ny))
            b = int(235 + 20 * ny)
            a = 255
            # 圆角矩形遮罩（内边距 4%）
            pad = 0.04
            ix = min(nx, 1 - nx)
            iy = min(ny, 1 - ny)
            if ix >= pad and iy >= pad:
                pass  # 主体
                if ix < pad + 0.035 and iy < pad + 0.035:
                    # 圆角外
                    cxr, cyr = pad + 0.035, pad + 0.035
                    if ((nx - cxr) ** 2 + (ny - cyr) ** 2) > 0.035 ** 2:
                        a = 0
                elif ix < pad + 0.035 or iy < pad + 0.035:
                    a = 0
            else:
                a = 0
            # 白色对勾：两条线段，厚度 0.055
            if a:
                t = 0.055
                seg = [((0.28, 0.52), (0.44, 0.68)), ((0.44, 0.68), (0.72, 0.36))]
                chk = False
                for (x1, y1), (x2, y2) in seg:
                    # 点到线段距离
                    dx, dy = x2 - x1, y2 - y1
                    L2 = dx * dx + dy * dy
                    tt = max(0, min(1, ((nx - x1) * dx + (ny - y1) * dy) / L2 if L2 else 0))
                    pxp = x1 + tt * dx
                    pyp = y1 + tt * dy
                    if ((nx - pxp) ** 2 + (ny - pyp) ** 2) ** 0.5 <= t / 2:
                        chk = True
                        break
                if chk:
                    r = g = b = 255
            px.append((r, g, b, a))
    return px


def icon_image(size):
    """构造单张 ICO 图像数据（BITMAPINFOHEADER + 像素 + AND掩码）"""
    px = draw(size)
    header = struct.pack(
        '<IiiHHIIiiII',
        40,          # biSize
        size, size * 2,
        1, 32,
        0,           # BI_RGB
        len(px) * 4, size, size, 0, 0
    )
    # 像素：自下而上 BGRA
    body = b''
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = px[y * size + x]
            body += struct.pack('<BBBB', b, g, r, a)
    and_mask = b'\x00' * (size * size // 8 if size % 8 == 0 else (size + 7) // 8 * size)
    return header + body + and_mask


def make_ico(sizes=(16, 32, 48, 64, 128, 256), path='icon.ico'):
    images = []
    for s in sizes:
        data = icon_image(s)
        images.append((s, data))
    # ICONDIR
    out = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        w = 0 if s == 256 else s
        h = 0 if s == 256 else s
        out += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in images:
        out += data
    with open(path, 'wb') as f:
        f.write(out)
    print('icon.ico 已生成，大小:', len(out), 'bytes')


if __name__ == '__main__':
    make_ico(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico'))