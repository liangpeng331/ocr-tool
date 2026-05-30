#!/usr/bin/env python3
"""生成 OCR 工具应用图标 icon.icns —— 蓝色圆底 + 白色"字"字"""
import subprocess, os, shutil, sys

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONSET = os.path.join(OUT_DIR, "icon.iconset")
ICNS = os.path.join(OUT_DIR, "icon.icns")

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def find_chinese_font() -> str:
    """查找系统中有"字"字符的中文字体"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # fallback: search
    for root, _, files in os.walk("/System/Library/Fonts"):
        for f in files:
            if f.endswith(".ttc") or f.endswith(".ttf"):
                fp = os.path.join(root, f)
                try:
                    font = ImageFont.truetype(fp, 40)
                    if font.getmask("字"):
                        return fp
                except Exception:
                    pass
    return None


def generate_png(size: int, font_path: str, output: str):
    """生成 size x size 的 PNG 图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = max(2, size * 0.08)
    circle_box = [padding, padding, size - padding, size - padding]
    draw.ellipse(circle_box, fill=(0, 122, 255, 255))  # blue #007AFF

    # 白色"字"字，大小约为圆直径的 60%
    font_size = int(size * 0.58)
    font = ImageFont.truetype(font_path, font_size)
    text = "字"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, fill="white", font=font)

    img.save(output, "PNG")


def main():
    font_path = find_chinese_font()
    if not font_path:
        print("ERROR: 找不到中文字体！请安装 PingFang 等字体。")
        sys.exit(1)
    print(f"使用字体: {font_path}")

    # 创建 .iconset 目录
    if os.path.exists(ICONSET):
        shutil.rmtree(ICONSET)
    os.makedirs(ICONSET)

    # 生成各尺寸
    for s in SIZES:
        name = f"icon_{s}x{s}.png"
        path = os.path.join(ICONSET, name)
        generate_png(s, font_path, path)
        print(f"  {name} ({s}x{s})")

        # @2x 版本（命名约定：16x16@2x = 32x32 实际像素）
        if s <= 512:
            s2 = s * 2
            name2 = f"icon_{s}x{s}@2x.png"
            path2 = os.path.join(ICONSET, name2)
            generate_png(s2, font_path, path2)
            print(f"  {name2} ({s2}x{s2})")

    # 用 iconutil 打包为 .icns
    print(f"\n打包 {ICNS} ...")
    subprocess.run(["iconutil", "-c", "icns", "-o", ICNS, ICONSET], check=True)

    # 清理临时目录
    shutil.rmtree(ICONSET)
    print("完成！icon.icns 已生成。")


if __name__ == "__main__":
    main()
