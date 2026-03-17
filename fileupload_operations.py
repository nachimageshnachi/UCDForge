import streamlit as st
import xml.etree.ElementTree as ET
from connection import connection
class fileupload_operations:
    def __init__(self,file_name):
        self._file_name = file_name
        
    @staticmethod
    def createTables():

        with connection.get_cursor() as cursor:
            schema_sql = """
            CREATE TABLE IF NOT EXISTS systems (
                id INT AUTO_INCREMENT PRIMARY KEY,
                system_name VARCHAR(255) UNIQUE,
                description TEXT,
                domain VARCHAR(255)
            );

            CREATE TABLE IF NOT EXISTS actors (
                id INT AUTO_INCREMENT PRIMARY KEY,
                actor_name VARCHAR(255),
                system_name VARCHAR(255),
                actor_type VARCHAR(100),
                actor_reference_number INT DEFAULT 700 CHECK (actor_reference_number IN (700, 703)),
                FOREIGN KEY (system_name) REFERENCES systems(system_name)
            );

            CREATE TABLE IF NOT EXISTS use_cases (
                id INT AUTO_INCREMENT PRIMARY KEY,
                use_case_name VARCHAR(255),
                system_name VARCHAR(255),
                description TEXT,
                category VARCHAR(100),
                FOREIGN KEY (system_name) REFERENCES systems(system_name)
            );

            CREATE TABLE IF NOT EXISTS relations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                source_name VARCHAR(255),
                target_name VARCHAR(255),
                system_name VARCHAR(255),
                source_type ENUM('actor', 'Use case'),
                target_type ENUM('actor', 'Use case'),
                relation_name VARCHAR(255),
                relation_code INT,
                extension VARCHAR(255),
                FOREIGN KEY (system_name) REFERENCES systems(system_name)
            );
            """
            
            for statement in schema_sql.strip().split(";"):
                if statement.strip():
                    cursor.execute(statement + ";")

        print("Created Tables")
        
    @staticmethod
    def destroyTables():

        with connection.get_cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in ['relations', 'actors', 'use_cases', 'systems']:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        print("Destroyed Tables")
    
    @staticmethod
    def clearTables():

        with connection.get_cursor() as cursor:

            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

            cursor.execute("DELETE FROM relations")
            cursor.execute("DELETE FROM actors")
            cursor.execute("DELETE FROM use_cases")
            cursor.execute("DELETE FROM systems")

            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        print("Cleared Tables")
        
    def addToDb(self):
        try:
            with connection.get_cursor() as cursor:
                tree = ET.parse(self._file_name)
                root = tree.getroot()
                modeling_elems = [
                    m for m in root.findall('Modeling')
                    if m.attrib.get('type') in ('Avatar Analysis', 'Analysis')
                ]
                if not modeling_elems:
                    st.error("No Use Case Diagram Found in File!")
                    return
                
                for modeling in modeling_elems:
                    usecasediagrampanel = modeling.find('UseCaseDiagramPanel')
                    if usecasediagrampanel is None:
                        st.error(f"No Use Case Diagram present in {modeling}")
                        continue
                    
                    name_of_ucd = usecasediagrampanel.attrib.get('name')
                    
                    stickman_actors=[]
                    box_actors=[]
                    use_cases=[]
                    system_boundary=[]

                    print(f"The Name of the Use Case Diagram is : {name_of_ucd}")

                    for component in usecasediagrampanel.findall('COMPONENT'):
                        if component.attrib.get('type') == '700':
                            stickman_actors.append(component.find('infoparam').attrib.get('value'))
                        elif component.attrib.get('type') == '701':
                            use_cases.append(component.find('infoparam').attrib.get('value'))
                        elif component.attrib.get('type') == '702':
                            system_name = component.find('infoparam').attrib.get('value')
                            system_boundary.append(system_name)
                        elif component.attrib.get('type') == '703':
                            box_actors.append(component.find('infoparam').attrib.get('value'))
                    
                    if len(system_boundary) != 1:
                        st.error(f"It is advisable to have exactly 1 System per Use Case Diagram, Therefore I am skipping Use Case Diagram present in {modeling}")
                        continue
                            
                    cursor.execute("SELECT 1 FROM systems WHERE system_name = %s LIMIT 1",(system_name,))
                    system = cursor.fetchone()
                    if system is None:
                        cursor.execute("INSERT INTO systems (system_name) VALUES (%s)",(system_name,))
                    else:
                        st.error(f"System '{system_name}' already exists")
                        continue
                    
                    for actor in stickman_actors:
                        cursor.execute("INSERT INTO actors (actor_name, system_name) VALUES (%s,%s)",(actor,system_name,))

                    for use_case in use_cases:
                        cursor.execute("INSERT INTO use_cases (use_case_name, system_name) VALUES (%s,%s)",(use_case,system_name,))

                    for actor in box_actors:
                        cursor.execute("INSERT INTO actors (actor_name, system_name, actor_reference_number) VALUES (%s,%s,%s)",(actor,system_name,703,))

                    for connector in usecasediagrampanel.findall('CONNECTOR'):
                        extension=''
                        relation_code = connector.attrib.get('type')
                        relation_name = connector.find('infoparam').attrib.get('name')
                        value = connector.find('infoparam').attrib.get('value')
                        source = connector.find('P1').attrib.get('id')
                        target = connector.find('P2').attrib.get('id')
                        
                        for component in usecasediagrampanel.findall('COMPONENT'):
                            for connectingpoint in component.findall('TGConnectingPoint'):
                                if source == connectingpoint.attrib.get('id'):
                                    source_name = component.find('infoparam').attrib.get('value')
                                    source_type = component.find('infoparam').attrib.get('name')
                                    if value.__contains__('extend'):
                                        extension = component.find('extraparam').find('info').attrib.get('extension')
                            
                                elif target == connectingpoint.attrib.get('id'):
                                    target_name = component.find('infoparam').attrib.get('value')
                                    target_type = component.find('infoparam').attrib.get('name')
                        
                        if value.__contains__('extend'):
                            cursor.execute('INSERT INTO relations (source_name, target_name, system_name, source_type, target_type, relation_name, relation_code, extension) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',(source_name,target_name,system_name,source_type,target_type,relation_name,relation_code,extension,))

                        else:
                            cursor.execute('INSERT INTO relations (source_name, target_name, system_name, source_type, target_type, relation_name, relation_code) VALUES (%s,%s,%s,%s,%s,%s,%s)',(source_name,target_name,system_name,source_type,target_type,relation_name,relation_code,))      
                connection.commit()
                st.success("Use Case Diagram Data uploaded and processed successfully.")
                print('Use Case Diagram Data Inserted Successfully')
        except Exception as e:
            connection.rollback()
            st.error(f"Unexpected error please contact the admin: {e}")
            print(f"DB Insert Error: {e}")
