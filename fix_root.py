import os

SERVER_PY = r"d:\GBOC-New\GBOC-New\GBOC-Server\gboc_server.py"

def fix_root():
    with open(SERVER_PY, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    out_lines = []
    skip = False
    for i, line in enumerate(lines):
        # Detect the start of the bad function
        if ("@app.get('/')" in line or '@app.get("/")' in line) and i + 1 < len(lines) and "async def root_redirect" in lines[i+1]:
            skip = True
            
        if skip:
            # We are inside the bad block. Wait until we see the end of it.
            if "</html>''')" in line or "</body></html>" in line:
                skip = False
            continue
            
        out_lines.append(line)
        
    new_content = '\n'.join(out_lines)

    if new_content != content:
        with open(SERVER_PY, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Fixed root route!")
    else:
        print("Nothing changed.")

if __name__ == '__main__':
    fix_root()
