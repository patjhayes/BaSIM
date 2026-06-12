from html.parser import HTMLParser

class MyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.line_offset = 0

    def handle_starttag(self, tag, attrs):
        if tag not in ['br', 'img', 'hr', 'input', 'path', 'meta', 'link', 'svg']:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag not in ['br', 'img', 'hr', 'input', 'path', 'meta', 'link', 'svg']:
            if len(self.stack) == 0:
                print(f"Extra end tag </{tag}> at line {self.getpos()[0]}")
            elif self.stack[-1][0] == tag:
                self.stack.pop()
            else:
                print(f"Mismatched end tag: Expected </{self.stack[-1][0]}>, got </{tag}> at line {self.getpos()[0]}. Open tag was at line {self.stack[-1][1][0]}")
                while len(self.stack) > 0 and self.stack[-1][0] != tag:
                    self.stack.pop()
                if len(self.stack) > 0:
                    self.stack.pop()

with open('c:/Users/patri/OneDrive/BaSIM v2.0/BaSIM_v1.0_source/frontend/src/views/DesignView.vue', 'r', encoding='utf-8') as f:
    data = f.read()

template = data.split('<script setup')[0]
parser = MyHTMLParser()
parser.feed(template)
for tag, pos in parser.stack:
    print(f"Unclosed tag: <{tag}> at line {pos[0]}")
