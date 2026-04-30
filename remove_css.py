import os
import re

def process_html_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Ensure {% load static %} is at the top if it's an HTML file
    if file_path.endswith('.html') and not content.strip().startswith('{% load static %}'):
        content = '{% load static %}\n' + content

    # 2. Remove existing <style>...</style> blocks
    content = re.sub(r'<style.*?>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # 3. Remove style="..." attributes
    content = re.sub(r'\sstyle="[^"]*"', '', content, flags=re.IGNORECASE)
    content = re.sub(r"\sstyle='[^']*'", '', content, flags=re.IGNORECASE)

    # 4. Remove ALL existing <link> tags that are stylesheets or link to .css files
    # This regex is designed to be more robust against quote types by explicitly matching single or double quotes
    # and not embedding the string delimiter in the character class.
    # It looks for link tags with rel="stylesheet" or href ending in .css
    css_link_regex = r'<link[^>]*?(?:rel=["\']stylesheet["\']|href=["\'][^"\']*?\.css["\'])[^>]*?>'
    content = re.sub(css_link_regex, '', content, flags=re.DOTALL | re.IGNORECASE)

    # 5. Add/Ensure the new responsive CSS link in base.html and admin_base.html
    new_css_link = '<link rel="stylesheet" href="{% static 'style.css' %}">'
    
    target_files = ['base.html', 'admin_base.html']

    if os.path.basename(file_path) in target_files:
        if new_css_link not in content:
            if '</head>' in content:
                content = content.replace('</head>', f'    {new_css_link}\n</head>')
            else:
                # Fallback if </head> is not found, though unlikely for valid HTML
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
