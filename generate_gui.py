import yaml
import os

# Configuration
CONFIG_FILE = 'config.yaml'
TEMPLATE_FILE = 'row_template.bob'
OUTPUT_FILE = 'main.bob'
ROW_HEIGHT = 40  # Vertical spacing between rows

def generate_bob():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found.")
        return

    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f)
        pv_list = config.get('pvs', [])

    # Header for Phoebus Display Builder XML
    xml_content = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<display version="2.0.0">',
        '  <name>PVwatcher Main Display</name>',
        '  <width>800</width>',
        f'  <height>{len(pv_list) * ROW_HEIGHT + 50}</height>'
    ]

    # Generate an Embedded Display widget for each PV in the YAML
    for i, pv_name in enumerate(pv_list):
        y_pos = i * ROW_HEIGHT
        xml_content.append(f'''
  <widget type="embedded" version="2.0.0">
    <name>Row_{i}</name>
    <file>{TEMPLATE_FILE}</file>
    <x>0</x>
    <y>{y_pos}</y>
    <width>800</width>
    <height>{ROW_HEIGHT}</height>
    <macros>
      <PV>{pv_name}</PV>
    </macros>
  </widget>''')

    xml_content.append('</display>')

    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(xml_content))
    
    print(f"Successfully generated {OUTPUT_FILE} with {len(pv_list)} rows.")

if __name__ == "__main__":
    generate_bob()
