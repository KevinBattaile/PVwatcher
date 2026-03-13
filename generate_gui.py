import yaml

def generate_main_bob(config_path='config.yaml', output_path='main.bob'):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    pvs = config.get('target_pvs', {})
    prefix = config.get('prefix', 'MONITOR:')

    # Calculate total window height dynamically
    base_rows_height = len(pvs) * 40
    notification_height = 350
    total_height = 110 + base_rows_height + notification_height

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<display version="2.0.0">',
        '  <name>PVwatcher Dashboard</name>',
        f'  <width>800</width><height>{total_height}</height>',
        '  <widget type="rectangle" version="2.0.0">',
        '    <width>800</width><height>60</height>',
        '    <background_color><color name="Header_Background" red="200" green="200" blue="200"/></background_color>',
        '  </widget>',
        '  <widget type="label" version="2.0.0">',
        '    <text>SYSTEM STATE:</text><x>10</x><y>15</y><width>150</width><font><size>18</size><style>BOLD</style></font>',
        '  </widget>',
        '  <widget type="multi_state_led" version="2.0.0">',
        f'    <pv_name>{prefix}SUMMARY_STATUS</pv_name><x>170</x><y>20</y><width>20</width><height>20</height>',
        '    <states>',
        '      <state><value>0</value><label></label><color><color red="255" green="0" blue="0"/></color></state>',
        '      <state><value>1</value><label></label><color><color red="0" green="255" blue="0"/></color></state>',
        '      <state><value>2</value><label></label><color><color red="150" green="150" blue="150"/></color></state>',
        '    </states>',
        '  </widget>',
        '  <widget type="combo" version="2.0.0">',
        f'    <pv_name>{prefix}MASTER_ENABLE</pv_name><x>210</x><y>15</y><width>150</width><height>30</height>',
        '    <items_from_pv>true</items_from_pv>',
        '  </widget>'
    ]

    # --- ALIGNED HEADERS ---
    headers = [
        ("PV Name", 10), ("Description", 250), ("Value", 410), 
        ("Enable", 500), ("Low", 600), ("High", 670), ("Status", 730)  
    ]
    for text, x_pos in headers:
        xml.append(f'  <widget type="label" version="2.0.0">')
        xml.append(f'    <text>{text}</text><x>{x_pos}</x><y>80</y><width>90</width><font><style>BOLD</style></font>')
        xml.append('  </widget>')

    y_offset = 110
    # Generate Target PV Rows
    for pv, pv_info in pvs.items():
        desc = pv_info.get('desc', 'No Desc') if isinstance(pv_info, dict) else pv_info
        xml.append(f'  <widget type="template" version="2.0.0">')
        xml.append(f'    <file>row_template.bob</file><instances><instance><macros><PV>{pv}</PV><DESC>{desc}</DESC></macros></instance></instances>')
        xml.append(f'    <x>0</x><y>{y_offset}</y><width>800</width><height>40</height>')
        xml.append('  </widget>')
        y_offset += 40

    y_offset += 20 # Spacing

    # --- NOTIFICATION CONTROLS ---
    xml.append('  <widget type="label" version="2.0.0">')
    xml.append(f'    <text>NOTIFICATIONS</text><x>10</x><y>{y_offset}</y><width>200</width><font><size>16</size><style>BOLD</style></font>')
    xml.append('  </widget>')
    y_offset += 30

    # Master Slack
    xml.append(f'''  <widget type="label" version="2.0.0"><text>Slack Alerts</text><x>10</x><y>{y_offset}</y><width>100</width></widget>
  <widget type="multi_state_led" version="2.0.0">
    <pv_name>{prefix}SLACK:STATUS</pv_name><x>120</x><y>{y_offset}</y><width>20</width><height>20</height>
    <states>
      <state><value>0</value><label></label><color><color red="255" green="0" blue="0"/></color></state>
      <state><value>1</value><label></label><color><color red="0" green="255" blue="0"/></color></state>
      <state><value>2</value><label></label><color><color red="150" green="150" blue="150"/></color></state>
    </states>
  </widget>
  <widget type="combo" version="2.0.0"><pv_name>{prefix}SLACK:ENABLE</pv_name><x>160</x><y>{y_offset-5}</y><width>100</width><height>30</height></widget>''')
    y_offset += 40

    # Master Email
    xml.append(f'''  <widget type="label" version="2.0.0"><text>Email Alerts</text><x>10</x><y>{y_offset}</y><width>100</width></widget>
  <widget type="multi_state_led" version="2.0.0">
    <pv_name>{prefix}EMAIL:STATUS</pv_name><x>120</x><y>{y_offset}</y><width>20</width><height>20</height>
    <states>
      <state><value>0</value><label></label><color><color red="255" green="0" blue="0"/></color></state>
      <state><value>1</value><label></label><color><color red="0" green="255" blue="0"/></color></state>
      <state><value>2</value><label></label><color><color red="150" green="150" blue="150"/></color></state>
    </states>
  </widget>
  <widget type="combo" version="2.0.0"><pv_name>{prefix}EMAIL:ENABLE</pv_name><x>160</x><y>{y_offset-5}</y><width>100</width><height>30</height></widget>''')
    y_offset += 40

    # 6 Email Recipient Slots
    for i in range(1, 7):
        xml.append(f'''  <widget type="label" version="2.0.0"><text>Recipient {i}</text><x>50</x><y>{y_offset}</y><width>100</width></widget>
  <widget type="textentry" version="3.0.0">
    <pv_name>{prefix}EMAIL:REC{i}:ADDR</pv_name><x>160</x><y>{y_offset}</y><width>250</width><height>20</height>
    <format>6</format>
  </widget>
  <widget type="combo" version="2.0.0"><pv_name>{prefix}EMAIL:REC{i}:ENABLE</pv_name><x>420</x><y>{y_offset-5}</y><width>100</width><height>30</height></widget>''')
        y_offset += 35

    y_offset += 20
    # Last Update Block
    xml.append('  <widget type="label" version="2.0.0">')
    xml.append(f'    <text>Last Update:</text><x>10</x><y>{y_offset}</y><width>100</width><font><style>ITALIC</style></font>')
    xml.append('  </widget>')
    xml.append('  <widget type="textupdate" version="2.0.0">')
    f_pv = f"{prefix}LAST_UPDATE"
    xml.append(f'    <pv_name>{f_pv}</pv_name><x>110</x><y>{y_offset}</y><width>200</width><height>20</height>')
    xml.append('    <format>6</format>')
    xml.append('    <background_color><color name="Read_Background" red="240" green="240" blue="240"/></background_color>')
    xml.append('  </widget>')
    xml.append('</display>')
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(xml))
    print(f"Generated {output_path} with live Notification Controls.")

if __name__ == "__main__":
    generate_main_bob()
