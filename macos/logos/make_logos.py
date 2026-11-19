from PIL import Image, ImageDraw, ImageFont
P = {"B":"#6cb4ee","G":"#8fcf7f","O":"#d97757","A":"#e5b85c","T":"#5ec4b6","F":"#9fe0d6",
     "K":"#1a1918","W":"#6cb4ee","R":"#e48ba3","Y":"#f3e3b5","C":"#a9a49c"}
LOGOS = {
 "buddy": ("Buddy", "A little helper with a sprout on its head", [
  "................",
  "......GG..GG....",
  ".......GGGG.....",
  "........GG......",
  "........G.......",
  "...BBBBBBBBBB...",
  "..BBBBBBBBBBBB..",
  "..BBBBBBBBBBBB..",
  "..BBBKKBBBKKBB..",
  "..BBBKKBBBKKBB..",
  "..BBRBBBBBBBRB..",
  "..BBBBBKKKBBBB..",
  "..BBBBBBBBBBBB..",
  "...BBBBBBBBBB...",
  "................",
  "................"]),
 "sprout": ("Sprout", "Growing a little every day", [
  "................",
  ".GGG........GGG.",
  ".GGGGG....GGGGG.",
  "..GGGGG..GGGGG..",
  "...GGGGGGGGGG...",
  ".....GGGGGG.....",
  ".......GG.......",
  ".......GG.......",
  ".......GG.......",
  "...OOOOOOOOOO...",
  "...OOOOOOOOOO...",
  "....OOOOOOOO....",
  "....OOOOOOOO....",
  ".....OOOOOO.....",
  "................",
  "................"]),
 "star": ("North Star", "Points you to what matters", [
  ".......AA.......",
  ".......AA.......",
  "......AAAA......",
  "......AAAA......",
  ".....AAAAAA.....",
  "..AAAAAAAAAAAA..",
  "AAAAAAAKKAAAAAAA",
  "AAAAAAAKKAAAAAAA",
  "..AAAAAAAAAAAA..",
  ".....AAAAAA.....",
  "......AAAA......",
  "......AAAA......",
  ".......AA.......",
  ".......AA.......",
  "................",
  "................"]),
 "hearth": ("Hearth", "Home base, light on", [
  "...........CC...",
  ".......OO..CC...",
  "......OOOO.CC...",
  ".....OOOOOOCC...",
  "....OOOOOOOOO...",
  "...OOOOOOOOOOO..",
  "..OOOOOOOOOOOOO.",
  "...WWWWWWWWWWW..",
  "...WAAAWWWWKKW..",
  "...WAAAWWWWKKW..",
  "...WWWWWWWWKKW..",
  "...WWWWWWWWKKW..",
  "................",
  "................",
  "................",
  "................"]),
 "owl": ("Owl", "Wise, watchful, a bit cute", [
  "..TT........TT..",
  "..TTT......TTT..",
  "..TTTTTTTTTTTT..",
  ".TTYYYTTTTYYYTT.",
  ".TTYKYTTTTYKYTT.",
  ".TTYYYTOOTYYYTT.",
  ".TTTTTTOOTTTTTT.",
  ".TTTTTTTTTTTTTT.",
  ".TTFFFFFFFFFFTT.",
  ".TTFFFFFFFFFFTT.",
  "..TTFFFFFFFFTT..",
  "...TTTTTTTTTT...",
  "....OO....OO....",
  "................",
  "................",
  "................"]),
}
def bbox(rows):
    ys=[y for y,r in enumerate(rows) if r.strip(".")]; xs=[x for r in rows for x,c in enumerate(r) if c!="."]
    return min(xs),min(ys),max(xs),max(ys)
def render(rows, S=1024):
    img=Image.new("RGBA",(S,S),(0,0,0,0)); d=ImageDraw.Draw(img)
    m=100; d.rounded_rectangle([m,m,S-m,S-m],radius=185,fill="#262624",outline="#3e3d3a",width=6)
    x0,y0,x1,y1=bbox(rows); w,h=x1-x0+1,y1-y0+1
    px=min(560//w,560//h); ox=(S-w*px)//2; oy=(S-h*px)//2
    for y,r in enumerate(rows):
        for x,c in enumerate(r):
            if c!=".": d.rectangle([ox+(x-x0)*px,oy+(y-y0)*px,ox+(x-x0+1)*px-1,oy+(y-y0+1)*px-1],fill=P[c])
    return img
tiles=[]
for k,(name,tag,rows) in LOGOS.items():
    assert all(len(r)==16 for r in rows),k
    im=render(rows); im.save(f"logo-{k}.png"); im.save(f"logo-{k}.icns",sizes=[(16,16),(32,32),(64,64),(128,128),(256,256),(512,512),(1024,1024)])
    tiles.append((name,tag,im))
# contact sheet
T=360; sheet=Image.new("RGB",(len(tiles)*(T+40)+40, T+150),"#1f1e1d"); d=ImageDraw.Draw(sheet)
try: f1=ImageFont.truetype("/root/.local/share/fonts/JetBrainsMonoNerdFontMono-Bold.ttf",26); f2=ImageFont.truetype("/root/.local/share/fonts/JetBrainsMonoNerdFontMono-Regular.ttf",17)
except Exception: f1=f2=ImageFont.load_default()
for i,(name,tag,im) in enumerate(tiles):
    x=40+i*(T+40); sheet.paste(im.resize((T,T),Image.NEAREST),(x,20),im.resize((T,T),Image.NEAREST))
    d.text((x+T/2,T+40),f"{i+1}. {name}",fill="#ece9e4",font=f1,anchor="mm"); d.text((x+T/2,T+80),tag,fill="#a9a49c",font=f2,anchor="mm")
sheet.save("logo-options.png"); print("ok")
