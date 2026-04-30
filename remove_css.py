import os
import re

def process_html_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove existing <style>...</style> blocks
    content = re.sub(r'<style.*?>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. Remove style="..." attributes
    content = re.sub(r'\sstyle="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r"\sstyle='[^']*'", '', content, flags=re.IGNORECASE)

    # 3. Remove existing CSS link tags
    content = re.sub(r'<link[^>]*rel=["\']stylesheet["\'][^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<link[^>]*href=[^>]*\.css[^>]*>', '', content, flags=re.IGNORECASE)

    # 4. Add the new responsive CSS link
    new_css_link = '<link rel="stylesheet" href="/static/style.css">'
    if '</head>' in content:
        content = content.replace('</head>', f'    {new_css_link}\n</head>')
    elif '<body>' in content: # Fallback if no head, though unlikely for valid HTML
        content = content.replace('<body>', f'<head>\n    {new_css_link}\n</head>\n<body>')
    else: # If neither head nor body, just prepend
        content = f'<head>\n    {new_css_link}\n</head>\n{content}'

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def process_templates(root_dir):
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                print(f"Processing {file_path}...")
                process_html_file(file_path)

if __name__ == "__main__":
    process_templates('templates')
