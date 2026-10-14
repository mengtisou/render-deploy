from PIL import Image, ImageDraw, ImageFilter, ImageFont

BG = (15, 34, 45); GRID = (27, 55, 70); CYAN = (56, 189, 248); CYAN2 = (90, 209, 238)
ORANGE = (247, 147, 30); ICE = (224, 242, 254); WHITE = (248, 250, 252)
HEAD = (24, 52, 68); FACE = (9, 22, 30); SLATE = (92, 114, 128)


def glow(img, box, color, blur, alpha=120):
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(box, fill=color + (alpha,))
    g = g.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(g)


def bolt(d, cx, top, h, outline=ORANGE, fill=ICE, edge=CYAN):
    """The logo's bolt: light fill, orange outline, a cyan inner edge."""
    w = h * 0.62
    pts = [(cx + w * 0.20, top), (cx - w * 0.42, top + h * 0.58), (cx - w * 0.02, top + h * 0.56),
           (cx - w * 0.22, top + h), (cx + w * 0.44, top + h * 0.38), (cx + w * 0.04, top + h * 0.41)]
    off = h * 0.045
    d.polygon([(x + off, y + off * 0.4) for x, y in pts], fill=outline)
    d.polygon([(x - off * 0.5, y) for x, y in pts], fill=edge)
    d.polygon(pts, fill=fill)


def robot(S: int, scale: float = 1.0, with_bg=True) -> Image.Image:
    """The RealAI bot on an S×S square (drawn 4× bigger, then reduced for smooth edges)."""
    K = 4
    N = S * K
    im = Image.new("RGBA", (N, N), BG + (255,) if with_bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = N / 100 * scale                                   # 1 unit = 1 % of the canvas
    cx = N / 2
    if with_bg:
        for i in range(0, 101, 8):                        # chart grid
            d.line([(i * N / 100, 0), (i * N / 100, N)], fill=GRID, width=int(N / 400))
            d.line([(0, i * N / 100), (N, i * N / 100)], fill=GRID, width=int(N / 400))
        glow(im, (cx - 38 * u, N / 2 - 30 * u, cx + 38 * u, N / 2 + 40 * u), CYAN, 9 * u, 70)
        d = ImageDraw.Draw(im)
        # rising arrow behind the head (the logo's trend line)
        pts = [(cx - 44 * u, N / 2 + 30 * u), (cx - 30 * u, N / 2 + 14 * u), (cx - 18 * u, N / 2 + 22 * u),
               (cx + 30 * u, N / 2 - 16 * u), (cx + 40 * u, N / 2 - 24 * u)]
        d.line(pts, fill=CYAN + (110,), width=int(2.2 * u), joint="curve")
        ax, ay = pts[-1]
        d.polygon([(ax + 4 * u, ay - 4 * u), (ax - 4.5 * u, ay - 1.5 * u), (ax + 1.5 * u, ay + 4.5 * u)], fill=CYAN + (140,))
    top = N / 2 - 14 * u                                  # head box
    hw, hh = 30 * u, 27 * u
    # antenna + bolt
    d.line([(cx, top - 1 * u), (cx, top - 9 * u)], fill=CYAN2, width=int(2.2 * u))
    d.ellipse((cx - 2.6 * u, top - 11.5 * u, cx + 2.6 * u, top - 6.3 * u), fill=CYAN2)
    glow(im, (cx - 9 * u, top - 34 * u, cx + 9 * u, top - 8 * u), ORANGE, 4 * u, 70)
    d = ImageDraw.Draw(im)
    bolt(d, cx, top - 33 * u, 22 * u)
    # ears
    for sx in (-1, 1):
        ex = cx + sx * (hw + 2.2 * u)
        d.rounded_rectangle((ex - 3.2 * u, top + 9 * u, ex + 3.2 * u, top + 21 * u), radius=2.2 * u, fill=CYAN2)
    # head
    d.rounded_rectangle((cx - hw - 0.9 * u, top - 0.9 * u, cx + hw + 0.9 * u, top + hh * 2 + 0.9 * u), radius=10 * u, fill=CYAN)
    d.rounded_rectangle((cx - hw, top, cx + hw, top + hh * 2), radius=9.5 * u, fill=HEAD)
    # face screen
    fx, fy, fw, fh = cx - hw + 5 * u, top + 5 * u, (hw - 5 * u) * 2, hh * 2 - 10 * u
    d.rounded_rectangle((fx, fy, fx + fw, fy + fh), radius=7 * u, fill=FACE)
    # eyes (glowing)
    ey = fy + 13 * u
    for sx in (-1, 1):
        ex = cx + sx * 11 * u
        glow(im, (ex - 7 * u, ey - 7 * u, ex + 7 * u, ey + 7 * u), CYAN, 2.5 * u, 150)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((ex - 4.2 * u, ey - 5.2 * u, ex + 4.2 * u, ey + 5.2 * u), radius=4 * u, fill=CYAN2)
        d.ellipse((ex - 1.6 * u, ey - 3.8 * u, ex + 1.2 * u, ey - 1.2 * u), fill=WHITE)
    # mouth: the logo's candlesticks, low → high
    bars = [(SLATE, 3.2), ((120, 140, 152), 5.0), (ICE, 6.6), ((140, 180, 205), 8.2), (CYAN2, 10.0), (WHITE, 12.0)]
    bw, gap = 3.2 * u, 2.3 * u
    total = len(bars) * bw + (len(bars) - 1) * gap
    base = fy + fh - 4.5 * u
    x = cx - total / 2
    for col, hgt in bars:
        h = hgt * u * 0.82
        d.line([(x + bw / 2, base - h - 1.6 * u), (x + bw / 2, base + 1.2 * u)], fill=col, width=int(0.7 * u))
        d.rounded_rectangle((x, base - h, x + bw, base), radius=0.5 * u, fill=col)
        x += bw + gap
    return im.resize((S, S), Image.LANCZOS)


if __name__ == "__main__":
    import os
    os.chdir("/home/user/render-deploy/telegram-bot-images")
    # profile photo: the head sits inside Telegram's circle
    pic = robot(640, scale=0.92).convert("RGB")
    pic.save("telegram-bot-profile-640.png", optimize=True)
    pic.save("telegram-bot-profile-640.jpg", quality=95)
    prev = Image.new("RGB", (640, 640), (24, 24, 27))
    mask = Image.new("L", (640, 640), 0); ImageDraw.Draw(mask).ellipse((0, 0, 639, 639), fill=255)
    prev.paste(pic, (0, 0), mask)
    prev.resize((320, 320), Image.LANCZOS).save("preview-bot-circle.png")

    # description banner 640×360 with the bot
    W, H = 640, 360
    ban = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(ban)
    for x in range(0, W, 32):
        d.line([(x, 0), (x, H)], fill=GRID)
    for y in range(0, H, 32):
        d.line([(0, y), (W, y)], fill=GRID)
    bot = robot(330, scale=0.95, with_bg=False)
    glow(ban, (40, 50, 300, 320), CYAN, 45, 55)
    ban.alpha_composite(bot, (-5, 25))
    d = ImageDraw.Draw(ban)
    F = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    t1, t1b, t2, t3 = (ImageFont.truetype(F, 50), ImageFont.truetype(F, 30), ImageFont.truetype(FR, 20),
                       ImageFont.truetype(F, 16))
    x0 = 318
    d.text((x0, 78), "Real", font=t1, fill=(241, 245, 249))
    d.text((x0 + d.textlength("Real", font=t1), 78), "AI", font=t1, fill=CYAN)
    d.text((x0 + 2, 136), "BOT", font=t1b, fill=ORANGE)
    d.text((x0 + 2, 182), "Gold trading signals", font=t2, fill=(203, 213, 225))
    d.text((x0 + 2, 210), "& market news — live", font=t2, fill=(203, 213, 225))
    d.rounded_rectangle((x0, 254, x0 + 222, 288), radius=17, fill=CYAN)
    d.text((x0 + 17, 262), "XAUUSD · KTR · OFX", font=t3, fill=BG)
    ban = ban.convert("RGB")
    ban.save("telegram-bot-description-640x360.png", optimize=True)
    ban.save("telegram-bot-description-640x360.jpg", quality=95)
    print("ok")
