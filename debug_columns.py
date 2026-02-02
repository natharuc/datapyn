"""Debug script para verificar colunas"""
import pyodbc

# Simular cursor.description
class MockCursor:
    description = [
        ('id', int),
        ('Name', str),
        ('EMAIL', str),
        ('created_at', str)
    ]

cursor = MockCursor()
columns = [col[0] for col in cursor.description]
print("Colunas extraídas:", columns)
print("Case preservado?", columns == ['id', 'Name', 'EMAIL', 'created_at'])
