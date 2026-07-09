from docx import Document
from pathlib import Path
p=Path(r'D:\parking_board_agent\tmp_simple.docx')
d=Document(); d.add_paragraph('hello 测试'); d.save(p)
print(p)
