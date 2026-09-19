"""產生本專案自有、無個人資料的 PDF 匯入案例；僅產生時需要 ReportLab。"""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pdfencrypt import StandardEncryption

ROOT = Path(__file__).resolve().parent
font = UnicodeCIDFont('MSung-Light')
# MSung-Light 使用 CNS1；明確指定，避免產生器預設 GB 映射造成不合法組合。
font.encodingName = 'UniCNS-UCS2-H'
pdfmetrics.registerFont(font)


def create(name, pages, *, encrypted=False):
    encryption = StandardEncryption('fixture-password') if encrypted else None
    pdf = canvas.Canvas(str(ROOT / name), pagesize=(650, 842), invariant=True, encrypt=encryption)
    pdf.setTitle('PDF 匯入回歸測試資料')
    pdf.setAuthor('Stock Terminal 測試')
    for rows in pages:
        for x, y, text, font in rows:
            pdf.setFont(font, 12)
            pdf.drawString(x, y, text)
        pdf.showPage()
    pdf.save()


create('中文多頁計畫.pdf', [
    [(30, 790, '下週執行總表', 'MSung-Light'),
     (30, 740, '台積電 2330 買區 900～920 站穩 925 突破 950 破 880 減碼 破 850 出場', 'MSung-Light'),
     (30, 700, '倉位角色', 'MSung-Light'),
     (30, 670, '台積電：主倉。', 'MSung-Light')],
    [(30, 790, '聯發科 2454 買區 1100～1150 站穩 1160 突破 1200 破 1080 減碼 破 1000 出場', 'MSung-Light'),
     (30, 740, '聯發科：觀察倉。', 'MSung-Light')],
])
create('一般多頁文字.pdf', [
    [(30, 740, 'First page: PDF import compatibility.', 'Helvetica')],
    [(30, 740, 'Second page: text stays on this device.', 'Times-Roman')],
])
create('密碼保護.pdf', [[(30, 740, 'Encrypted fixture.', 'Helvetica')]], encrypted=True)
create('空白文件.pdf', [[]])
(ROOT / '損毀文件.pdf').write_bytes(b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog\n')
