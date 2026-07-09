from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
indir=Path(r'D:\parking_board_agent\rendered_competition_final')
imgs=sorted(indir.glob('page-*.png'))
thumbs=[]
for p in imgs:
    im=Image.open(p).convert('RGB')
    im.thumbnail((330, 455))
    thumbs.append((p, im.copy()))
cols=4
W=cols*360; H=((len(thumbs)+cols-1)//cols)*520
sheet=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(sheet)
try: font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',24)
except: font=ImageFont.load_default()
for idx,(p,im) in enumerate(thumbs):
    x=(idx%cols)*360+15; y=(idx//cols)*520+45
    d.text((x,y-35),p.stem,font=font,fill=(0,0,0))
    sheet.paste(im,(x,y))
sheet.save(indir/'contact_sheet.png')
print(indir/'contact_sheet.png')
