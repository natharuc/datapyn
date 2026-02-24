"""
Font Manager - Gerencia fontes customizadas empacotadas com o app.

A fonte Ubuntu vem empacotada no diretorio assets/fonts e eh registrada
via QFontDatabase no startup do app.
"""

import logging
from pathlib import Path

from PyQt6.QtGui import QFontDatabase, QFont

logger = logging.getLogger(__name__)

# Caminho da pasta fonts relativo a este arquivo
FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"


def get_fonts_directory() -> Path:
    """Retorna o caminho da pasta de fontes."""
    return FONTS_DIR


def register_fonts() -> int:
    """
    Registra todas as fontes da pasta fonts no QFontDatabase.
    
    Returns:
        Numero de fontes registradas com sucesso
    """
    fonts_dir = get_fonts_directory()
    
    if not fonts_dir.exists():
        logger.warning(f"Pasta de fontes nao existe: {fonts_dir}")
        return 0
    
    registered = 0
    
    for font_file in fonts_dir.glob("*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.debug(f"Fonte registrada: {font_file.name} -> {families}")
            registered += 1
        else:
            logger.warning(f"Falha ao registrar fonte: {font_file.name}")
    
    return registered


def initialize_fonts() -> bool:
    """
    Inicializa o sistema de fontes: registra as fontes empacotadas.
    
    Deve ser chamado apos QApplication ser criado.
    
    Returns:
        True se pelo menos a fonte principal foi registrada
    """
    logger.info("Inicializando sistema de fontes...")
    
    # Registrar todas as fontes da pasta assets/fonts
    registered = register_fonts()
    logger.info(f"Fontes registradas no Qt: {registered}")
    
    # Verificar se Ubuntu esta disponivel
    families = QFontDatabase.families()
    ubuntu_available = "Ubuntu" in families
    
    if ubuntu_available:
        logger.info("Fonte Ubuntu disponivel com sucesso")
    else:
        logger.warning("Fonte Ubuntu nao encontrada, usando fallback")
    
    return ubuntu_available


def get_application_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """
    Retorna a fonte padrao do aplicativo.
    
    Args:
        size: Tamanho da fonte em pontos
        weight: Peso da fonte (Normal, Medium, Bold, Light)
        
    Returns:
        QFont configurada com Ubuntu ou fallback
    """
    font = QFont()
    
    # Verificar se Ubuntu esta disponivel
    families = QFontDatabase.families()
    
    if "Ubuntu" in families:
        font.setFamily("Ubuntu")
    else:
        # Fallbacks
        font.setFamilies([
            "Ubuntu",
            "Roboto",
            "Segoe UI",
            "-apple-system",
            "sans-serif"
        ])
    
    font.setPointSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    
    return font


def get_monospace_font(size: int = 10) -> QFont:
    """
    Retorna a fonte monospace do aplicativo.
    
    Args:
        size: Tamanho da fonte em pontos
        
    Returns:
        QFont monospace (Ubuntu Mono ou fallback)
    """
    font = QFont()
    
    # Verificar se Ubuntu Mono esta disponivel
    families = QFontDatabase.families()
    
    if "Ubuntu Mono" in families:
        font.setFamily("Ubuntu Mono")
    else:
        # Fallbacks
        font.setFamilies([
            "Ubuntu Mono",
            "Cascadia Code",
            "Fira Code",
            "Consolas",
            "Monaco",
            "monospace"
        ])
    
    font.setPointSize(size)
    
    return font


# Constantes de fonte para uso no CSS
FONT_FAMILY_PRIMARY = '"Ubuntu", "Roboto", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif'
FONT_FAMILY_MONO = '"Ubuntu Mono", "Cascadia Code", "Fira Code", "Consolas", "Monaco", monospace'
