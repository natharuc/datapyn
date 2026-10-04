# Notificações de execução no desktop Tauri

Cada conclusão guarda a identidade do workspace, sessão, bloco e execução. Trocar de aba ou de foco durante uma consulta não altera o destino do aviso. A conclusão apresenta sucesso, erro ou cancelamento; executar uma fila produz um aviso ao terminar ou no bloco que interrompeu a fila.

## Navegação e histórico

- Clique no aviso do aplicativo, no histórico ou no corpo/botão **Abrir resultado** da notificação Windows para ativar a sessão de origem e focar seu editor.
- O destino usa IDs estáveis: reorganizar blocos não troca o alvo. Um bloco recolhido expande; a maximização de outro bloco é removida; o dock do editor é exibido. Janelas principais/popouts minimizadas são restauradas.
- A conclusão não troca automaticamente a aba que o usuário está editando. A navegação acontece no clique. Um destino fechado ou pertencente a outro workspace informa que está indisponível e não executa código.
- **Notificações**, no menu superior, abre as últimas 100 entradas e o contador de não lidas. Há até três avisos simultâneos; cada um tem identidade e temporizador próprios. Passar o mouse ou focar um aviso pausa seu fechamento. Fechar o aviso preserva a entrada no histórico.
- O histórico é da instância atual e é limpo ao trocar de workspace. Não armazena código, credenciais, DataFrames ou linhas do resultado. Deduplicação, timers e destinos nativos têm limites independentes.

## Configuração compatível

O botão **Configurar notificações** no histórico abre as configurações existentes. `notifications.json` e `notification_config` do `.dpw` preservam seu formato e seus templates, regras, canais e cores.

Notificações e som vêm habilitados por padrão, como no PyQt6; preferências já salvas são respeitadas. Desabilitar notificações ou corresponder à regra **Suprimir notificação** suprime aviso local, som e canais externos. O som da notificação Windows respeita a preferência, inclusive com o aplicativo minimizado.

Templates e regras são renderizados no kernel antes de a próxima execução alterar as variáveis. Nome do bloco, conexão efetiva, database, erro e resultado pertencem à conclusão correspondente. Uma fila pode passar explicitamente sua última tabela ao Python final sem resultado; uma execução isolada sem tabela ou uma falha não usa um DataFrame antigo implicitamente. Cancelamento tem texto próprio quando os templates padrão estão em uso; templates personalizados são preservados.

## Entrega sem bloquear a interface

`execution.finished` leva apenas a notificação pública já renderizada. Telegram e SMTP são enviados em jobs separados depois de publicar a conclusão, sem colocar uma operação de rede na fila do editor. O resultado de entrega usa `notifications.delivery_finished` com a identidade capturada do workspace/execução.

Falhas na notificação Windows e nos canais externos aparecem junto da entrada correspondente no histórico. O aviso local continua disponível quando o Windows impede a entrega nativa. Credenciais permanecem no backend/keyring e não entram no evento ou no histórico.

A ponte Windows usa WinRT e a identidade isolada `app.datapyn.desktop.preview`. Na primeira entrega, cria o atalho **DataPyn Tauri Preview** no Menu Iniciar do usuário com esse AppUserModelID, ativador COM, ícone e caminho do executável. Se o portátil mudar de pasta, atualiza apenas o atalho que pertence à mesma identidade; um atalho estrangeiro não é substituído. A identidade preview não altera o atalho do PyQt6.

O corpo e o botão passam apenas um ID opaco ao ativador COM; o destino completo permanece no host. A implementação segue o [contrato de ativação desktop da Microsoft](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/send-local-toast-desktop-cpp-wrl) para `ToastGeneric`. Avisos removidos por limite/expiração também são removidos do histórico Windows. Startup e encerramento limpam somente o grupo de execuções da identidade preview, evitando avisos antigos sem destino em memória.

Na primeira entrega de um aplicativo não empacotado, `ToastNotifier.Setting` pode retornar `0x80070490` antes de existir o estado do remetente. Somente esse erro permite tentar `Show`; estados explicitamente desabilitados, outros HRESULTs e falhas de entrega continuam reportados. Nenhuma permissão ou política do Windows é alterada.

Cliques recebidos durante um reload da interface ficam pendentes até a confirmação do frontend. A navegação nativa cobre o processo aberto, em segundo plano ou minimizado; encerrar completamente o aplicativo encerra seus callbacks e não oferece relançamento por uma notificação antiga.

## Validação

Testes de `executionNotifications`, `nativeExecutionNotifications` e `workspace` cobrem avisos simultâneos, temporizadores, limites, deduplicação, foco alterado, reorganização/recolhimento/maximização, perfil incorreto, erro/cancelamento e entregas atrasadas. Testes de runtime cobrem o JSONL real, captura de templates antes da próxima execução, ausência de resultados antigos, filas, cancelamento, ordem de entrega e transportes externos simulados. Os 35 testes Rust validam destino, XML, som, ativação, retenção/ack, estado inicial/bloqueios do Windows, limpeza do histórico nativo, factory/callback COM reais e persistência COM real do atalho, incluindo relocação e proteção de uma identidade estrangeira.

O smoke de paridade exercita o contrato no sidecar congelado. Build de produção, TypeScript, Ruff, 485 testes frontend (49 arquivos), 510 testes runtime/compatibilidade e 35 testes Rust passaram em 4 de outubro de 2026. Canais externos reais não são acionados pelo aceite.

## Aceite no executável Windows

O roteiro usou SQLite, sessões/arquivos de teste isolados e canais externos desabilitados:

- SQL concluído e Python de 25 segundos produziram entradas próprias; trocar de aba durante a execução não mudou a aba selecionada ao terminar. Erro e cancelamento apareceram com mensagens distintas.
- O clique no aviso local marcou a entrada como lida e colocou o cursor no editor correto. O histórico navegou entre sessões, expandiu bloco recolhido, removeu a maximização de outro bloco e restaurou o popout minimizado.
- `ToastNotificationManager.History.GetHistoryWithId` confirmou notificações reais do AUMID preview, com grupo `executions`, tags próprias e `launch=datapyn-open:<id>` correto.
- Um probe separado chamou o callback real via `SCM.CoCreateInstance` e `INotificationActivationCallback.Activate`, usando a tag do Python realmente entregue. Retornou `S_OK`, restaurou a janela minimizada, mudou da sessão de erro para a sessão de origem, marcou o aviso como lido e focou o bloco Python 2, sem executar seu código novamente.
- Encerrar normalmente a instância removeu todos os avisos do grupo: a leitura seguinte do histórico Windows retornou zero entradas.

A automação desta máquina não expôs a janela do banner/da Central de Notificações. A entrega e a ativação COM foram verificadas pelas APIs reais; o clique físico no corpo e no botão do banner/Central permanece um aceite visual separado. O som foi configurado como silencioso no roteiro; seu XML e sua preferência têm cobertura automatizada.
