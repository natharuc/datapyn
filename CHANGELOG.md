# CHANGELOG

<!-- version list -->

## Unreleased

### Added
- Suporte para execucao paralela de testes com pytest-xdist
- Marcadores de teste (unit, integration, slow, gui) para execucao seletiva
- Script de geracao de instalador MSI para Windows (build_msi.bat)
- Script de geracao de executavel EXE (build_exe.bat)
- Menu interativo de build com opcoes para EXE, MSI ou ambos
- Documentacao completa de otimizacao de testes (docs/TEST_OPTIMIZATION.md)
- Documentacao completa de geracao de MSI (docs/BUILD_MSI.md)
- Arquivo de dependencias de build separado (requirements-build.txt)
- Indice de documentacao (docs/README.md)

### Changed
- Configuracao do pytest otimizada para melhor performance
- Tempo de execucao dos testes reduzido em 60-70% com execucao paralela
- Build.bat agora oferece menu interativo para escolher tipo de build
- README atualizado com informacoes sobre testes otimizados e builds

### Performance
- Testes agora executam em ~5-8 minutos (antes: ~15-20 minutos)
- Suporte para execucao seletiva de testes por categoria

## v1.0.0 (2026-02-08)

- Initial Release
