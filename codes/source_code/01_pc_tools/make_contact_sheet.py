from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
indir=Path(r'D:\parking_board_agent\rendered_flowchart_docx')
imgs=sorted(indir.glob('page-*.png'))
thumbs=[]
for p in imgs:
    im=Image.open(p).convert('RGB')
    im.thumbnail((350, 470))
    thumbs.append((p, im.copy()))
W=4*380; H=((len(thumbs)+3)//4)*530
sheet=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(sheet)
try: font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',24)
except: font=ImageFont.load_default()
for idx,(p,im) in enumerate(thumbs):
    x=(idx%4)*380+15; y=(idx//4)*530+45
    d.text((x,y-35),p.stem,font=font,fill=(0,0,0))
    sheet.paste(im,(x,y))
sheet.save(indir/'contact_sheet.png')
print(indir/'contact_sheet.png')
