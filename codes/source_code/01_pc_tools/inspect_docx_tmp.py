from docx import Document
from pathlib import Path
p=Path(r'C:\Users\Cheng\Desktop\嵌入式大赛作品报告_视觉闭环自主泊车系统_增强版.docx')
print('exists', p.exists(), p.stat().st_size if p.exists() else None)
doc=Document(str(p))
for i,para in enumerate(doc.paragraphs):
    t=' '.join(para.text.split())
    if t:
        print(f'{i:04d} [{para.style.name}] {t[:160]}')
