#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把生图素材裁成网页横幅，并生成移动端版本。

生图模型输出多为 4:3（如 1536×1024），而横幅需要更宽的比例（约 3.7:1），
因此这里做一次智能裁切：优先保留右侧卡牌扇形，左侧留白区可安全裁掉部分。

输出：
  web/assets/hero.jpg          1920×520 桌面端
  web/assets/hero-mobile.jpg   1080×420 移动端（中心安全区构图）
"""
import os
import sys

from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "web", "assets")

SRC = os.path.join(ASSETS, "Wide_game_banner_background_fo_2026-10-20T07-03-09.png")
DESKTOP = os.path.join(ASSETS, "hero.jpg")
MOBILE = os.path.join(ASSETS, "hero-mobile.jpg")


def crop_to_aspect(img: Image.Image, ratio: float, anchor: float = 0.5) -> Image.Image:
    """
    裁切到目标比例。
    anchor: 0=靠左, 0.5=居中, 1=靠右。横幅主体在右侧，故用 0.62 左右。
    """
    w, h = img.size
    cur = w / h
    if cur > ratio:
        # 太宽 → 裁两侧
        nw = int(h * ratio)
        left = int((w - nw) * anchor)
        left = max(0, min(w - nw, left))
        return img.crop((left, 0, left + nw, h))
    # 太高 → 裁上下（保留偏上区域，卡牌在中上部）
    nh = int(w / ratio)
    top = int((h - nh) * 0.42)
    top = max(0, min(h - nh, top))
    return img.crop((0, top, w, top + nh))


def polish(img: Image.Image) -> Image.Image:
    """
    后期处理：
    1) 轻度高斯模糊——抹掉生图模型在卡面上生成的伪文字/伪数字
       （这类瑕疵在桌面端横幅尺寸下会被放大，模糊后完全不可辨）
    2) 提饱和 + 提对比，让金色更亮
    """
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    img = ImageEnhance.Color(img).enhance(1.14)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    return img


def main() -> int:
    if not os.path.exists(SRC):
        print(f"[FAIL] 找不到源图: {SRC}")
        return 1

    img = Image.open(SRC).convert("RGB")
    # 生图模型常在卡面生成不可辨识的伪文字，先整体柔化
    img = img.filter(ImageFilter.GaussianBlur(radius=2.2))
    print(f"源图: {img.size[0]}x{img.size[1]} ({img.size[0]/img.size[1]:.2f}:1)")

    # 桌面端 1920x520 ≈ 3.69:1，锚点偏右保卡牌
    d = crop_to_aspect(img, 1920 / 520, anchor=0.66)
    d = polish(d).resize((1920, 520), Image.LANCZOS)
    d.save(DESKTOP, "JPEG", quality=86, optimize=True, progressive=True)
    print(f"桌面端 hero.jpg        {d.size[0]}x{d.size[1]}  "
          f"{os.path.getsize(DESKTOP)/1024:.0f} KB")

    # 移动端 1080x420 ≈ 2.57:1，构图更方，卡牌需仍在视野内
    m = crop_to_aspect(img, 1080 / 420, anchor=0.70)
    m = polish(m).resize((1080, 420), Image.LANCZOS)
    m.save(MOBILE, "JPEG", quality=84, optimize=True, progressive=True)
    print(f"移动端 hero-mobile.jpg {m.size[0]}x{m.size[1]}  "
          f"{os.path.getsize(MOBILE)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())