import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('OUTPUT_DIR', '/tmp/llm_test')
from app.services.edinet import EdinetClient
edinet = EdinetClient()

# Download the latest annual report (有価証券報告書) for Casio - doc S100W670 (FY2025 ending Mar 2025)
details = edinet.extract_large_holder_details.__self__  # get the client instance

# Let's extract financial data from the annual report
zip_bytes = edinet.download_xbrl_zip('S100W670')
html_bytes = edinet._select_honbun_html(zip_bytes)

from bs4 import BeautifulSoup
import unicodedata
soup = BeautifulSoup(html_bytes, 'html.parser')
text = unicodedata.normalize('NFKC', soup.get_text())

# Save for inspection
with open('/tmp/casio_annual_text.txt', 'w') as f:
    f.write(text)

# Search for key financial figures
import re
# Revenue/Sales
print("=" * 80)
print("REVENUE (売上高) MATCHES:")
print("=" * 80)
for m in re.finditer(r'売上高.{0,100}', text):
    print(f'Revenue: {text[m.start():m.start()+150]}')
    print()

# Operating profit
print("=" * 80)
print("OPERATING PROFIT (営業利益) MATCHES:")
print("=" * 80)
for m in re.finditer(r'営業利益.{0,100}', text):
    print(f'OP: {text[m.start():m.start()+150]}')
    print()

# Total assets
print("=" * 80)
print("TOTAL ASSETS (総資産) MATCHES:")
print("=" * 80)
for m in re.finditer(r'総資産.{0,100}', text):
    print(f'Assets: {text[m.start():m.start()+150]}')
    print()

# Major shareholders
print("=" * 80)
print("MAJOR SHAREHOLDERS (大株主|主要な株主) MATCHES:")
print("=" * 80)
for m in re.finditer(r'大株主|主要な株主', text):
    start = m.start()
    print(f'Shareholders section at pos {start}:')
    print(text[start:start+500])
    print()

print("=" * 80)
print(f"Text saved to /tmp/casio_annual_text.txt ({len(text)} chars)")
print("=" * 80)
