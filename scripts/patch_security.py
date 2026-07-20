import os
import re
import secrets

def update_env_jwt():
    new_jwt = secrets.token_hex(32)
    files = ['.env', '.env.example']
    for f in files:
        if os.path.exists(f):
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
            content = re.sub(r'JWT_SECRET=.*', f'JWT_SECRET={new_jwt}', content)
            if 'JWT_SECRET=' not in content:
                content += f'\nJWT_SECRET={new_jwt}\n'
            
            with open(f, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f"Updated JWT_SECRET in {f}")

def patch_html_xss():
    html_files = ['admin.html', 'index.html', 'noticias.html']
    dompurify_script = '<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>'

    for hf in html_files:
        if not os.path.exists(hf):
            continue
        with open(hf, 'r', encoding='utf-8') as file:
            content = file.read()
        
        if 'purify.min.js' not in content:
            content = content.replace('</head>', f'    {dompurify_script}\n</head>')
        
        # We will carefully find instances of `.innerHTML = ` and replace them.
        # Since doing this perfectly with Regex is hard, we'll look for:
        # 1. innerHTML = `...`;
        # 2. innerHTML = "...";
        # 3. innerHTML = '...';
        # 4. innerHTML = '';
        
        # This function parses through the string to match backticks or quotes
        out_content = ""
        idx = 0
        while True:
            # find next innerHTML =
            found = content.find('.innerHTML = ', idx)
            if found == -1:
                out_content += content[idx:]
                break
            
            # append everything up to '.innerHTML = '
            out_content += content[idx:found + 13]
            idx = found + 13
            
            # skip whitespaces
            while idx < len(content) and content[idx] in ' \t\n\r':
                out_content += content[idx]
                idx += 1
                
            char = content[idx]
            if char in ["'", '"', "`"]:
                start_quote = char
                # find matching quote
                start_idx = idx
                idx += 1
                while idx < len(content):
                    if content[idx] == '\\':
                        idx += 2
                        continue
                    if content[idx] == start_quote:
                        idx += 1
                        break
                    idx += 1
                
                assignment = content[start_idx:idx]
                
                # Check for empty assignments to skip DOMPurify overhead
                if assignment in ["''", '""', "``"]:
                    out_content += assignment
                else:
                    out_content += f"DOMPurify.sanitize({assignment})"
            else:
                # It's some variable assignment like innerHTML = var_name;
                # find until semicolon
                start_idx = idx
                while idx < len(content) and content[idx] != ';':
                    idx += 1
                assignment = content[start_idx:idx]
                out_content += f"DOMPurify.sanitize({assignment})"
                
        with open(hf, 'w', encoding='utf-8') as file:
            file.write(out_content)
        print(f"Patched XSS vulnerabilities in {hf}")

if __name__ == '__main__':
    update_env_jwt()
    patch_html_xss()
