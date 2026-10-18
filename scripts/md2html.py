"""Convert a brief's markdown file into simple HTML for email. Usage: md2html.py IN.md OUT.html"""
import html
import re
import sys


def md_to_html(md):
    out, in_list = [], False
    for line in md.splitlines():
        l = line.rstrip()
        if not l:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        e = html.escape(l)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
        e = re.sub(r"(https?://[^\s<)]+)", r'<a href="\1">\1</a>', e)
        if l.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{e[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if l.startswith("#### "):
            out.append(f"<h4>{e[5:]}</h4>")
        elif l.startswith("### "):
            out.append(f"<h3>{e[4:]}</h3>")
        elif l.startswith("## "):
            out.append(f"<h2>{e[3:]}</h2>")
        elif l.startswith("# "):
            out.append(f"<h1>{e[2:]}</h1>")
        else:
            out.append(f"<p>{e}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    open(dst, "w").write(md_to_html(open(src).read()))
    print(dst)
