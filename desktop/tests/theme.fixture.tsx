import React from "react";
import { createRoot } from "react-dom/client";
import { ChevronDown, Database, Filter, Folder, Plus, RefreshCw, Search, Star } from "lucide-react";
import { AgentIcon } from "../src/AgentIcon";
import "dockview-react/dist/styles/dockview.css";
import "../src/docking.css";
import "../src/connections.css";
import "../src/explorer.css";
import "../src/blockScopePicker.css";
import "../src/resultGrid.css";
import "../src/dataActions.css";
import "../src/columnHeaderPopup.css";
import "../src/chartPanel.css";
import "../src/packages.css";
import "../src/pynia.css";
import "../src/pyniaOutput.css";
import "../src/notificationCenter.css";
import "../src/syntaxDiagnostics.css";
import "../src/variableArchive.css";
import "../src/styles.css";

// Isolated presentation fixture: real workbench CSS and DOM structures, no
// application startup, IPC, user profile, or database access.
function ThemeFixture() {
  return <main id="theme-fixture">
    <div className="app-header"><span className="brand"><span>DataPyn</span></span><div className="app-menu"><button>Abrir</button><button>Configurações</button><button>Exibir</button></div></div>
    <div className="session-bar"><div className="session-tab"><button role="tab"><span>Análise 1</span></button></div><div className="session-tab active"><button role="tab"><span>Análise 2</span></button></div></div>
    <div className="workspace-toolbar"><button className="connection-button"><Database size={14}/><span>GREEN</span><ChevronDown size={12}/></button><button className="primary-button run-button">Executar <kbd>F5</kbd></button><button className="text-button">Executar tudo</button></div>
    <div className="preview-grid">
      <section className="preview-panel connections-sidebar">
        <div className="connections-active"><Database size={15}/><div><strong>GREEN</strong><small>mysql · green</small></div></div>
        <div className="connections-toolbar"><strong>Conexões</strong><button className="icon-button"><RefreshCw size={14}/></button></div>
        <div className="connections-search"><Search size={14}/><input aria-label="Buscar conexões" placeholder="Buscar conexões"/><button className="icon-button"><Star size={14}/></button></div>
        <div className="connection-tree-row group"><Folder size={14}/><span>MAG</span></div><div className="connection-tree-row selected active"><Database size={14}/><span>GREEN</span></div>
      </section>
      <section className="preview-panel object-explorer">
        <div className="explorer-toolbar"><strong>Object Explorer</strong><button className="icon-button"><RefreshCw size={14}/></button></div>
        <div className="explorer-search"><Search size={14}/><input aria-label="Filtrar objetos" placeholder="Filtrar objetos…"/></div>
        <div className="explorer-row selected"><Database size={14}/><span>banco107atual</span></div><div className="explorer-row schema"><Folder size={14}/><span>financeiro</span></div>
        <p className="explorer-hint">Objetos do banco selecionado.</p>
      </section>
      <section className="preview-panel variable-inspector">
        <div className="variable-filter"><label><Search size={14}/><input aria-label="Filtrar variáveis" placeholder="Filtrar variáveis…"/></label></div>
        <div className="data-form"><label className="variable-archive-search"><Search size={13}/><input aria-label="Buscar arquivos" placeholder="Filtrar variáveis…"/></label></div>
      </section>
    </div>
    <div className="code-block sql focused"><div className="block-header"><span className="block-index">01</span><select className="language-select sql" aria-label="Linguagem"><option>SQL</option></select><input className="block-name" placeholder="Nome do resultado (df)"/><button className="block-scope"><Database size={13}/><span>GREEN</span></button><div className="block-scope-picker"><button className="block-scope-trigger"><span className="block-scope-label">Banco</span><span className="block-scope-value">green</span><ChevronDown size={12}/></button></div><button className="block-run">▶</button></div><div className="syntax-diagnostics warning"><div className="syntax-summary"><button>1 aviso</button><button className="syntax-first">L2:C7 Coluna desconhecida 'a'</button></div></div><pre className="preview-code">SELECT * FROM acesso</pre></div>
    <div className="add-block-row"><button><Plus size={12}/>SQL</button><button><Plus size={12}/>Python</button></div>
    <section className="results-panel"><div className="bottom-tabs"><button className="active">Resultados</button><button>Saída</button></div><div className="result-tabs"><button className="active">df <span>14.769</span></button><button>clientes</button></div><div className="grid-toolbar"><span className="result-meta">14.769 linhas / 29 colunas</span><label className="grid-filter"><Filter size={12}/><input aria-label="Filtrar resultados" placeholder="Filtrar valores…"/></label><button className="text-button">Copiar</button></div></section>
    <section className="datapyn-dock dockview-theme-light preview-dock"><div className="dv-groupview dv-active-group"><div className="dv-tabs-and-actions-container"><div className="dv-tabs-container"><div className="dv-tab dv-active-tab">Análise</div><div className="dv-tab dv-inactive-tab">Conexões</div></div></div></div></section>
    <div className="preview-grid">
      <section className="preview-panel modal connection-dialog"><header className="modal-header"><h2>Conexão</h2></header><form><div className="driver-options"><button type="button" className="selected">MySQL</button><button type="button">PostgreSQL</button><button type="button">Databricks</button></div><label className="field">Servidor<input placeholder="localhost"/></label><p className="field-note">Banco e schema selecionados.</p><footer className="modal-footer"><button className="secondary-button" type="button">Cancelar</button><button className="primary-button" type="button">Salvar</button></footer></form></section>
      <section className="preview-panel block-scope-popover"><div className="block-scope-search"><Search size={13}/><input role="combobox" aria-label="Pesquisar banco" placeholder="Pesquisar banco"/><button><RefreshCw size={13}/></button></div><div className="block-scope-option active current">green</div><div className="block-scope-option">analytics</div><div className="block-scope-message">2 bancos</div></section>
      <section className="preview-panel pynia-panel"><header className="pynia-header"><AgentIcon agentId="codex"/><strong>Pynia</strong><small>Codex</small></header><div className="pynia-messages"><div className="pynia-message user">Analisar o resultado</div><div className="pynia-message"><div className="pynia-markdown"><p>Resultado da consulta.</p><pre><code>df.head()</code></pre></div></div></div><div className="pynia-composer"><textarea aria-label="Mensagem" placeholder="Mensagem"/><div className="pynia-composer-controls"><button className="secondary-button">Enviar</button></div></div></section>
      <section className="preview-panel modal pynia-agent-settings"><header className="modal-header"><h2>Agentes Pynia</h2></header><div className="pynia-agent-list">{[["claude","Claude"],["cursor","Cursor"],["copilot","GitHub Copilot"],["codex","Codex"]].map(([id,label])=><section key={id}><header><AgentIcon agentId={id} label={label}/><strong>{label}</strong><small>Pronto</small></header><p>Instalação disponível.</p><div><button className="secondary-button">Instalar / atualizar</button><button className="primary-button">Usar agente</button></div></section>)}</div></section>
    </div>
    <footer className="statusbar"><span className="status-runtime ready"><span className="connection-dot"/>Runtime conectado</span><span className="status-message">Pronto</span></footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<ThemeFixture/>);
(window as Window & { themeFixtureReady?: boolean }).themeFixtureReady=true;
