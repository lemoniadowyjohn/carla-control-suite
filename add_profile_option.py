#!/usr/bin/env python
with open('ultimate_pipeline/cli.py', 'r') as f:
    content = f.read()

# Add the --profile option after --verbose
old = "@click.option(\"--verbose\", \"-v\", is_flag=True, help=\"Show detailed output\")\ndef doctor"

new = """@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--profile", type=click.Choice(["core", "offline-map", "research", "carla-runtime"]), default="core", help="Doctor profile to use")
def doctor"""

if old in content:
    content = content.replace(old, new)
    with open('ultimate_pipeline/cli.py', 'w') as f:
        f.write(content)
    print('Replacement successful')
else:
    print('Old string not found!')
    # Debug
    idx = content.find('@click.option("--verbose"')
    if idx >= 0:
        print(f'Found at index {idx}')
        print(content[idx:idx+100])
"