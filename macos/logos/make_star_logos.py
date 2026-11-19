import math, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, __import__("os").path.dirname(__file__))
from make_logos import LOGOS
COL = {"A":"#e5b85c","L":"#f3d58a","D":"#c08a3a","K":"#1a1918","C":"#6d6963","O":"#d97757","Q":"#a9553b","F":"#8a7044","Y":"#f6e7bd"}
N = 25; c = 12

def grid(): return [["." for _ in range(N)] for _ in range(N)]

def ray(g, ang_deg, L, W, light="L", deep="D", cx=c, cy=c):
    u = (math.sin(math.radians(ang_deg)), -math.cos(math.radians(ang_deg)))  # 0 = up
    v = (-u[1], u[0])
    for y in range(N):
        for x in range(N):
            px, py = x - cx, y - cy
            a = px*u[0] + py*u[1]; b = px*v[0] + py*v[1]
            if -0.5 <= a <= L and abs(b) <= W*(1 - max(a,0)/L) + 0.15:
                g[y][x] = light if b < 0 else deep

def disc(g, cx, cy, r, col):
    for y in range(N):
        for x in range(N):
            if (x-cx)**2 + (y-cy)**2 <= r*r: g[y][x] = col

def ring(g, cx, cy, R, t, col):
    for y in range(N):
        for x in range(N):
            if abs(math.hypot(x-cx, y-cy) - R) <= t: g[y][x] = col

def line(g, x0, y0, x1, y1, col):
    n = int(max(abs(x1-x0), abs(y1-y0))*2)+1
    for i in range(n+1):
        t = i/n; x = round(x0+(x1-x0)*t); y = round(y0+(y1-y0)*t)
        if g[y][x] == ".": g[y][x] = col

def poly(g, pts, col):
    for y in range(N):
        for x in range(N):
            px, py = x, y; inside = False; j = len(pts)-1
            for i in range(len(pts)):
                xi, yi = pts[i]; xj, yj = pts[j]
                if (yi > py) != (yj > py) and px < (xj-xi)*(py-yi)/(yj-yi)+xi: inside = not inside
                j = i
            if inside: g[y][x] = col

def compass_rose():
    g = grid()
    for a in (45, 135, 225, 315): ray(g, a, 7.5, 1.9, light="D", deep="D")
    for a in (0, 90, 180, 270): ray(g, a, 12, 3.2)
    disc(g, c, c, 1.2, "K"); return g

def needle():
    g = grid()
    ring(g, c, c, 11, 0.6, "D")
    for (x, y) in ((c, 1), (c, 23), (1, c), (23, c)): g[y][x] = "A"
    for y in range(N):
        for x in range(N):
            px, py = x-c, y-c
            if abs(px)/3.6 + abs(py)/9.5 <= 1: g[y][x] = ("L" if px < 0 else "A") if py <= 0 else "C"
    disc(g, c, c, 1.0, "K"); return g

def horizon():
    g = grid()
    for y in range(N):
        for x in range(N):
            if y <= 23 and (x-8)**2/42 + (y-24)**2/30 <= 1: g[y][x] = "Q"
            if y <= 23 and (x-16)**2/48 + (y-25)**2/36 <= 1: g[y][x] = "O"
    for a in (45, 135, 225, 315): ray(g, a, 3.8, 1.3, light="D", deep="D", cy=9)
    for a in (0, 90, 180, 270): ray(g, a, 8, 2.4, cy=9)
    return g

def constellation():
    g = grid()
    pts = [(3, 22), (6, 16), (11, 13), (16, 9)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = 6
        for i in range(2, n-1, 2):
            t = i/n; x = round(x0+(x1-x0)*t); y = round(y0+(y1-y0)*t); g[y][x] = "F"
    for (x, y) in pts[:3]: disc(g, x, y, 1.1, "A")
    for a in (45, 135, 225, 315): ray(g, a, 3.6, 1.4, cx=16, cy=8)
    for a in (0, 90, 180, 270): ray(g, a, 7, 2.2, cx=16, cy=8)
    return g

def burst():
    g = grid()
    for i in range(12):
        a = i*30; L = 12 if i % 3 == 0 else 9
        ray(g, a, L, 1.5, light="A", deep="A")
    disc(g, c, c, 5.2, "A"); disc(g, c-1, c-1, 2.4, "L"); return g

def five_point():
    g = grid()
    pts = []
    for i in range(10):
        r = 12 if i % 2 == 0 else 5
        a = math.radians(-90 + i*36)
        pts.append((c + r*math.cos(a), c + 1 + r*math.sin(a)))
    poly(g, pts, "A")
    # mirror the right half onto the left so the star is symmetric,
    # then light facets on the left, deeper on the right
    for y in range(N):
        for x in range(c):
            g[y][x] = g[y][2*c - x]
    for y in range(N):
        for x in range(N):
            if g[y][x] == "A": g[y][x] = "L" if x < c else ("A" if x == c else "D")
    disc(g, c, c+1, 1.0, "K"); return g

def to_rows(g): return ["".join(r) for r in g]

def render(rows, cols, S=1024, art=700):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    m = 100; d.rounded_rectangle([m, m, S-m, S-m], radius=185, fill="#262624", outline="#3e3d3a", width=6)
    ys = [y for y, r in enumerate(rows) if r.strip(".")]; xs = [x for r in rows for x, ch in enumerate(r) if ch != "."]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); w, h = x1-x0+1, y1-y0+1
    px = art // max(w, h); ox = (S - w*px)//2; oy = (S - h*px)//2
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch != ".": d.rectangle([ox+(x-x0)*px, oy+(y-y0)*px, ox+(x-x0+1)*px-1, oy+(y-y0+1)*px-1], fill=cols[ch])
    return img

OPTIONS = [
    ("star", "North Star", "the original", None),
    ("rose", "Compass Rose", "eight points, two-tone", compass_rose),
    ("needle", "Needle", "a compass pointing north", needle),
    ("horizon", "Over the Hills", "the star that guides you home", horizon),
    ("constellation", "Constellation", "Polaris and its little trail", constellation),
    ("burst", "Burst", "a warm, round star", burst),
    ("fivepoint", "Gold Star", "classic, with a bit of depth", five_point),
]
tiles = []
for key, name, tag, fn in OPTIONS:
    if fn is None:
        rows = LOGOS["star"][2]; cols = {"A": COL["A"], "K": COL["K"]}
        im = render(rows, cols, art=640)
    else:
        rows = to_rows(fn()); im = render(rows, COL)
    im.save(f"logo-{key}.png"); im.save(f"logo-{key}.icns", sizes=[(16,16),(32,32),(64,64),(128,128),(256,256),(512,512),(1024,1024)])
    tiles.append((name, tag, im))

T = 300; cols_n = 4; rows_n = 2
sheet = Image.new("RGB", (cols_n*(T+40)+40, rows_n*(T+120)+20), "#1f1e1d"); d = ImageDraw.Draw(sheet)
f1 = ImageFont.truetype("/root/.local/share/fonts/JetBrainsMonoNerdFontMono-Bold.ttf", 24)
f2 = ImageFont.truetype("/root/.local/share/fonts/JetBrainsMonoNerdFontMono-Regular.ttf", 16)
for i, (name, tag, im) in enumerate(tiles):
    x = 40 + (i % cols_n)*(T+40); y = 20 + (i // cols_n)*(T+120)
    t = im.resize((T, T), Image.LANCZOS); sheet.paste(t, (x, y), t)
    d.text((x+T/2, y+T+22), f"{i+1}. {name}", fill="#ece9e4", font=f1, anchor="mm")
    d.text((x+T/2, y+T+56), tag, fill="#a9a49c", font=f2, anchor="mm")
sheet.save("star-options.png"); print("ok")
