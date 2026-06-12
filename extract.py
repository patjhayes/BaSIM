import json

found = False
with open('C:/Users/patri/.gemini/antigravity-ide/brain/dae6f318-4010-4cc4-9507-ce9415ce3648/.system_generated/logs/transcript.jsonl', 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'USER_INPUT' and 'DesignView.vue' in data.get('content', ''):
            with open('user_input_designview.txt', 'w', encoding='utf-8') as out:
                out.write(data['content'])
            found = True
