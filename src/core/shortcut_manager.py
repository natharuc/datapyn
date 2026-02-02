"""
Gerenciador de atalhos de teclado configuráveis
"""
from typing import Dict, Callable
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget
import json
from pathlib import Path


class ShortcutManager:
    """Gerencia atalhos de teclado configuráveis"""
    
    DEFAULT_SHORTCUTS = {
        # Execução
        'execute_sql': 'F5',
        'execute_all': 'Ctrl+F5',
        'clear_results': 'Ctrl+Shift+C',
        
        # Arquivo
        'new_file': 'Ctrl+N',
        'open_file': 'Ctrl+O',
        'save_file': 'Ctrl+S',
        'save_as': 'Ctrl+Shift+S',
        
        # Sessões
        'new_tab': 'Ctrl+T',
        'close_tab': 'Ctrl+W',
        
        # Edição
        'find': 'Ctrl+F',
        'replace': 'Ctrl+H',
        
        # Conexões
        'manage_connections': 'Ctrl+Shift+M',
        'new_connection': 'Ctrl+Shift+D',
        
        # Ferramentas
        'settings': 'Ctrl+,',
    }
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path.home() / '.datapyn' / 'shortcuts.json'
        
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.shortcuts: Dict[str, str] = self._load_shortcuts()
        self.active_shortcuts: Dict[str, QShortcut] = {}
    
    def _load_shortcuts(self) -> Dict[str, str]:
        """Carrega atalhos do arquivo de configuração"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Migrar formato antigo
                    if 'shortcuts' in data:
                        return data['shortcuts']
                    return data
            except:
                pass
        return self.DEFAULT_SHORTCUTS.copy()
    
    def save_shortcuts(self):
        """Salva atalhos no arquivo de configuração"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump({'shortcuts': self.shortcuts}, f, indent=2)
    
    def get_shortcut(self, action: str) -> str:
        """Retorna o atalho para uma ação"""
        return self.shortcuts.get(action, '')
    
    def set_shortcut(self, action: str, key_sequence: str):
        """Define um novo atalho para uma ação"""
        self.shortcuts[action] = key_sequence
        self.save_shortcuts()
    
    def reset_to_defaults(self):
        """Reseta todos os atalhos para o padrão"""
        self.shortcuts = self.DEFAULT_SHORTCUTS.copy()
        self.save_shortcuts()
    
    def register_shortcut(self, parent: QWidget, action: str, callback: Callable):
        """Registra um atalho com callback"""
        key_sequence = self.get_shortcut(action)
        if key_sequence:
            shortcut = QShortcut(QKeySequence(key_sequence), parent)
            shortcut.activated.connect(callback)
            self.active_shortcuts[action] = shortcut
    
    def get_all_shortcuts(self) -> Dict[str, str]:
        """Retorna todos os atalhos configurados"""
        return self.shortcuts.copy()
