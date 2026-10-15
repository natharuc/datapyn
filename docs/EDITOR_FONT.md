# Fonte e zoom do editor

O tamanho do editor é um único valor em pixels, salvo nas preferências. Aceita
de 8 a 32 px com precisão de 0,1 px. Nas configurações, ponto e vírgula decimal
são aceitos; apagar ou digitar um valor parcial não muda a fonte antes de aplicar
ou sair do campo. Valores inválidos mantêm o tamanho anterior.

Ctrl/Cmd + roda do mouse altera esse mesmo tamanho em passos de 1 px. Eventos
pequenos do trackpad são acumulados para evitar saltos. A altura da linha é
calculada junto com a fonte, mantendo a proporção padrão de 13 px / 22 px.
As ações de aumentar, diminuir e restaurar fonte seguem a mesma regra.

O zoom global nativo do Monaco fica desativado. Não salvar o tamanho efetivo
de `onDidChangeConfiguration` como novo tamanho base: isso reaplica o fator
global em todos os blocos e provoca ampliação acumulativa. Configurações de
tema, autocomplete e foco também não devem sobrescrever o tamanho durante
uma sequência de rolagem.

Restauração de sessão e transferência de configurações Tauri preservam as
frações. O INI exportado para PyQt mantém fontes em pixels inteiros, conforme
o leitor histórico; `tauri-settings.json` guarda o valor fracionário exato.

Validação automatizada com Monaco e configurações reais em Chromium headless,
isolado do aplicativo instalado:

```powershell
npm --prefix desktop run test:editor-font
npm --prefix desktop run test:font-settings
```
