import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

// Isolated headless settings/form/trust fixture. No actual SSH, database, OS keyring or desktop is contacted.
const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."), route = "/__ssh_test";
const server = await createServer({ root, cacheDir: "node_modules/.vite-ssh-tests", plugins: [{ name: "ssh-fixture", configureServer(server) { server.middlewares.use(route, async (_request, response) => {
  response.setHeader("Content-Type", "text/html");
  response.end(await server.transformIndexHtml(route, '<!doctype html><html><body><div id="root"></div><script type="module" src="/tests/ssh.fixture.tsx"></script></body></html>'));
}); } }], server: { host: "127.0.0.1", port: 0, watch: null } });
let browser;
await server.listen();
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 960, height: 800 }, reducedMotion: "reduce" }), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const address = `http://127.0.0.1:${server.httpServer.address().port}${route}`;
  const settings = page.getByRole("dialog", { name: "Configurações", exact: true }), tunnel = page.locator(".ssh-tunnel-dialog"), connection = page.locator(".connection-dialog:not(.ssh-tunnel-dialog)"), trust = page.getByRole("dialog", { name: "Confirmar servidor SSH" });
  const lastCall = method => page.evaluate(method => JSON.parse(JSON.stringify(window.__SSH_TEST__.calls.filter(call => call.method === method).at(-1))), method);
  const noOverflow = async element => assert.equal(await element.evaluate(element => element.scrollWidth > element.clientWidth + 1), false);
  const openSettings = async () => { await page.getByRole("button", { name: "Configurações", exact: true }).click(); await settings.getByRole("button", { name: "Túneis SSH", exact: true }).click(); await settings.getByRole("button", { name: "Novo túnel", exact: true }).waitFor(); };
  const newConnection = async (name, database = "docfis") => {
    await page.getByRole("button", { name: "Nova conexão", exact: true }).click(); await connection.getByLabel("Tipo do banco").selectOption("postgresql");
    await connection.getByLabel("Nome", { exact: true }).fill(name); await connection.getByLabel("Servidor", { exact: true }).fill("pg.internal"); await connection.getByLabel("Banco", { exact: true }).fill(database);
    await connection.getByRole("combobox", { name: /^Túnel SSH/ }).selectOption("tunnel-1");
    assert.equal(await connection.getByLabel("Servidor SSH", { exact: true }).count(), 0); assert.equal(await connection.getByLabel("Senha SSH", { exact: true }).count(), 0); assert.equal(await connection.getByLabel("Usar túnel SSH").count(), 0);
  };
  for (const theme of ["light", "dark"]) {
    await page.goto(address); await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
    await openSettings(); await settings.getByRole("button", { name: "Novo túnel", exact: true }).click(); await tunnel.waitFor();
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await tunnel.getByRole("alert").filter({ hasText: "Informe o servidor" }).waitFor(); assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "ssh.tunnels.test").length), 0);
    await tunnel.getByLabel("Nome", { exact: true }).fill("VPS DocFis"); await tunnel.getByLabel("Servidor SSH", { exact: true }).fill("vps.example"); await tunnel.getByLabel("Usuário SSH", { exact: true }).fill("deploy"); await tunnel.getByLabel("Senha SSH", { exact: true }).fill("ssh-secret");
    assert.equal(await tunnel.getByLabel("Porta SSH", { exact: true }).inputValue(), "22");
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await trust.waitFor();
    assert((await trust.textContent()).includes("vps.example:22")); assert((await trust.textContent()).includes("SHA256:"));
    assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "connection.test").length), 0);
    assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "ssh.host_key.trust").length), 0);
    await trust.getByRole("button", { name: "Cancelar", exact: true }).click(); await tunnel.getByRole("alert").filter({ hasText: "cancelada" }).waitFor();
    assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "ssh.tunnels.test").length), 1);
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await trust.waitFor(); await trust.getByRole("button", { name: "Confiar e continuar", exact: true }).click(); await tunnel.getByRole("status").filter({ hasText: "SSH testada" }).waitFor();
    assert.equal((await lastCall("ssh.tunnels.test")).params.config.host, "vps.example"); assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "connection.test").length), 0);
    await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    let saved = (await lastCall("ssh.tunnels.save")).params;
    assert.equal(saved.password, "ssh-secret"); assert.equal(saved.save_credentials, true); assert.equal(saved.tunnel.config.password, undefined);
    await settings.getByRole("button", { name: "Editar túnel VPS DocFis", exact: true }).click(); await tunnel.waitFor();
    assert.equal(await tunnel.getByLabel("Senha SSH", { exact: true }).inputValue(), ""); assert.equal(await tunnel.getByLabel("Senha SSH", { exact: true }).getAttribute("placeholder"), "Deixe em branco para manter a senha salva");
    await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" }); assert.equal((await lastCall("ssh.tunnels.save")).params.password, undefined);
    await settings.getByRole("button", { name: "Editar túnel VPS DocFis", exact: true }).click(); await tunnel.getByLabel("Autenticação SSH").selectOption("private_key");
    assert.equal(await tunnel.getByLabel("Senha SSH", { exact: true }).count(), 0); await tunnel.getByRole("button", { name: "Escolher chave privada SSH", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.ssh-tunnel-dialog input[value="/keys/id_ed25519"]'));
    await tunnel.getByLabel("Passphrase (opcional)").fill("key-secret"); const longName = "DocFis VPS STG e PRD / " + "Infraestrutura corporativa ".repeat(8); await tunnel.getByLabel("Nome", { exact: true }).fill(longName);
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await tunnel.getByRole("status").filter({ hasText: "SSH testada" }).waitFor(); await noOverflow(tunnel);
    await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    saved = (await lastCall("ssh.tunnels.save")).params; assert.equal(saved.tunnel.id, "tunnel-1"); assert.equal(saved.passphrase, "key-secret"); assert.equal(saved.password, undefined); assert.equal(saved.tunnel.config.passphrase, undefined); await noOverflow(settings);
    await settings.getByRole("button", { name: `Editar túnel ${longName}`, exact: true }).click();
    assert.equal(await tunnel.getByLabel("Passphrase (opcional)").inputValue(), ""); assert.equal(await tunnel.getByLabel("Passphrase (opcional)").getAttribute("placeholder"), "Deixe em branco para manter a passphrase salva");
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await tunnel.getByRole("status").filter({ hasText: "SSH testada" }).waitFor();
    await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    assert.equal((await lastCall("ssh.tunnels.save")).params.passphrase, undefined);

    await settings.getByRole("button", { name: `Editar túnel ${longName}`, exact: true }).click(); await page.evaluate(() => window.__SSH_TEST__.resetTrust());
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await trust.waitFor();
    await page.evaluate(() => { document.querySelector('.ssh-tunnel-dialog .modal-header button').click(); }); await trust.waitFor({ state: "detached" }); await tunnel.waitFor({ state: "detached" });
    assert.equal(await page.evaluate(() => window.__SSH_TEST__.challenge), undefined);
    await settings.getByRole("button", { name: `Editar túnel ${longName}`, exact: true }).click(); await page.evaluate(() => { window.__SSH_TEST__.trusted.add("vps.example"); window.__SSH_TEST__.holdTests(); });
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 1);
    let testId = (await lastCall("ssh.tunnels.test")).params.test_id;
    await tunnel.getByRole("button", { name: "Cancelar teste", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 0); assert.equal((await lastCall("connection.test_cancel")).params.test_id, testId);
    await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 1); testId = (await lastCall("ssh.tunnels.test")).params.test_id;
    await tunnel.getByRole("button", { name: "Fechar", exact: true }).click(); await tunnel.waitFor({ state: "detached" }); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 0); assert.equal((await lastCall("connection.test_cancel")).params.test_id, testId);
    await page.evaluate(() => window.__SSH_TEST__.releaseTests()); await settings.getByRole("button", { name: "Fechar", exact: true }).last().click(); await settings.waitFor({ state: "detached" });

    for (const [name, database] of [["DocFis STG", "docfis_stg"], ["DocFis PRD", "docfis_prd"]]) {
      await newConnection(name, database); await connection.getByLabel("Senha", { exact: true }).fill("database-secret");
      await connection.getByText("TLS PostgreSQL", { exact: true }).click(); await connection.getByLabel("Modo TLS").selectOption("verify-full"); await connection.getByLabel("Certificado CA (opcional)").fill("/certs/ca.pem");
      await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "SSH e banco" }).waitFor();
      const tested = (await lastCall("connection.test")).params.config; assert.equal(tested.ssh_tunnel_id, "tunnel-1"); assert.equal(tested.ssh, undefined); assert.equal(tested.host, "pg.internal"); assert.equal(tested.sslmode, "verify-full");
      await noOverflow(connection); await connection.getByRole("button", { name: "Salvar", exact: true }).click(); await connection.waitFor({ state: "detached" });
      const save = (await lastCall("connections.save")).params; assert.equal(save.connection.config.ssh_tunnel_id, "tunnel-1"); assert.equal(save.connection.config.password, undefined); assert.equal(save.ssh_password, undefined); assert.equal(save.ssh_passphrase, undefined);
    }
    const publicCatalog = await page.evaluate(() => window.__SSH_TEST__.publicCatalog());
    assert.equal(publicCatalog.connections.length, 2); assert.equal(publicCatalog.ssh_tunnels.length, 1); assert(!JSON.stringify(publicCatalog).includes("key-secret")); assert(!JSON.stringify(publicCatalog).includes("database-secret"));
    await page.evaluate(() => window.__SSH_OPEN_EDIT__("connection-1")); await connection.waitFor();
    await connection.getByText("Colar connection string", { exact: true }).click(); await connection.getByLabel("URI ou string .NET/ODBC").fill("postgresql://reader:imported-password@pg.internal:5433/another_bank?sslmode=verify-full&sslrootcert=%2Fcerts%2Fca.pem"); await connection.getByRole("button", { name: "Preencher campos", exact: true }).click();
    assert.equal(await connection.getByRole("combobox", { name: /^Túnel SSH/ }).inputValue(), "tunnel-1"); await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "SSH e banco" }).waitFor();
    const edited = (await lastCall("connection.test")).params; assert.equal(edited.connection_id, "connection-1"); assert.equal(edited.resolve_database_password, false); assert.equal(edited.config.password, "imported-password"); assert.equal(edited.config.ssh_tunnel_id, "tunnel-1"); assert.equal(edited.config.port, 5433);
    await connection.getByRole("button", { name: "Gerenciar túneis SSH", exact: true }).click(); await settings.waitFor(); assert.equal(await settings.getByRole("button", { name: "Novo túnel", exact: true }).count(), 1);
    await settings.getByRole("button", { name: `Editar túnel ${longName}`, exact: true }).click(); await tunnel.getByLabel("Nome", { exact: true }).fill(`${longName} atualizado`); await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    assert.equal(await connection.getByRole("combobox", { name: "Túnel SSH", exact: true }).inputValue(), "tunnel-1"); assert.equal(await connection.getByRole("combobox", { name: "Túnel SSH", exact: true }).locator("option:checked").textContent(), `${longName} atualizado`);
    await settings.getByRole("button", { name: `Editar túnel ${longName} atualizado`, exact: true }).click(); await tunnel.getByLabel("Nome", { exact: true }).fill(longName); await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    await settings.getByRole("button", { name: `Excluir túnel ${longName}`, exact: true }).click(); const deleting = page.getByRole("dialog", { name: "Excluir túnel SSH" }); await deleting.getByRole("button", { name: "Excluir", exact: true }).click(); await deleting.getByRole("alert").filter({ hasText: "em uso" }).waitFor();
    assert.equal((await page.evaluate(() => window.__SSH_TEST__.publicCatalog())).ssh_tunnels.length, 1); await deleting.getByRole("button", { name: "Cancelar", exact: true }).click(); await settings.getByRole("button", { name: "Fechar", exact: true }).last().click();
    for (const [label, value] of [["Nome", "DocFis STG"], ["Servidor", "pg.internal"], ["Banco", "another_bank"], ["Usuário", "reader"], ["Senha", "imported-password"], ["Porta", "5433"]]) assert.equal(await connection.getByLabel(label, { exact: true }).inputValue(), value);
    assert.equal(await connection.getByRole("combobox", { name: "Túnel SSH", exact: true }).inputValue(), "tunnel-1"); assert.equal(await page.evaluate(() => document.activeElement.textContent), "Gerenciar túneis SSH");
    await connection.getByLabel("Tipo do banco").selectOption("sqlite"); assert.equal(await connection.getByRole("combobox", { name: /^Túnel SSH/ }).count(), 0); await connection.getByLabel("Tipo do banco").selectOption("postgresql"); assert.equal(await connection.getByRole("combobox", { name: /^Túnel SSH/ }).inputValue(), "");
    await connection.getByRole("combobox", { name: /^Túnel SSH/ }).selectOption("tunnel-1"); await connection.getByLabel("Tipo do banco").selectOption("databricks"); assert.equal(await connection.getByRole("combobox", { name: /^Túnel SSH/ }).count(), 0); await connection.getByLabel("Tipo do banco").selectOption("postgresql"); assert.equal(await connection.getByRole("combobox", { name: /^Túnel SSH/ }).inputValue(), "");
    await connection.getByRole("button", { name: "Cancelar", exact: true }).click(); await connection.waitFor({ state: "detached" });
    await newConnection("Teste cancelado"); await page.evaluate(() => window.__SSH_TEST__.holdTests());
    await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 1); testId = (await lastCall("connection.test")).params.test_id;
    await connection.getByRole("button", { name: "Fechar", exact: true }).click(); await connection.waitFor({ state: "detached" }); await page.waitForFunction(() => window.__SSH_TEST__.pendingTestCount === 0); assert.equal((await lastCall("connection.test_cancel")).params.test_id, testId); await page.evaluate(() => window.__SSH_TEST__.releaseTests());
    await openSettings(); await settings.getByRole("button", { name: "Novo túnel", exact: true }).click();
    await tunnel.getByLabel("Nome", { exact: true }).fill("Túnel sem referências"); await tunnel.getByLabel("Servidor SSH", { exact: true }).fill("unused.example"); await tunnel.getByLabel("Usuário SSH", { exact: true }).fill("deploy"); await tunnel.getByLabel("Senha SSH", { exact: true }).fill("unused-secret"); await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await tunnel.waitFor({ state: "detached" });
    await settings.getByRole("button", { name: "Excluir túnel Túnel sem referências", exact: true }).click(); await deleting.getByRole("button", { name: "Excluir", exact: true }).click(); await deleting.waitFor({ state: "detached" }); assert.equal((await page.evaluate(() => window.__SSH_TEST__.publicCatalog())).ssh_tunnels.length, 1); await settings.getByRole("button", { name: "Fechar", exact: true }).last().click(); await settings.waitFor({ state: "detached" });
    console.log(`PASS ${theme}: settings registration/edit, secure SSH password/key save, host trust/cancel, test cancellation, two database references, TLS/import independence, unsupported drivers and referenced deletion`);
  }
  for (const platform of ["windows", "linux", "macos"]) {
    await page.evaluate(platform => window.__SSH_TEST__.setPlatform(platform), platform);
    await page.getByRole("button", { name: "Nova conexão", exact: true }).click(); await connection.getByLabel("Tipo do banco").selectOption("sqlserver");
    const auth = connection.getByRole("combobox", { name: /^Autenticação/ }); await auth.locator('option[value="ntlm"]').waitFor({ state: "attached" });
    assert.equal(await auth.locator('option[value="windows"]').count(), platform === "windows" ? 1 : 0);
    await connection.getByLabel("Nome", { exact: true }).fill("Autenticação de rede"); await connection.getByLabel("Servidor", { exact: true }).fill("sql.internal"); await connection.getByLabel("Banco", { exact: true }).fill("esim");
    await auth.selectOption("ntlm"); await connection.getByLabel("Usuário", { exact: true }).fill("DOMAIN\\reader"); await connection.getByLabel("Senha", { exact: true }).fill("network-password"); await connection.getByLabel("Certificado CA (opcional)").fill("/certs/company.pem");
    await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "Conexão testada" }).waitFor();
    let config = (await lastCall("connection.test")).params.config; assert.equal(config.sqlserver_auth_mode, "ntlm"); assert.equal(config.username, "DOMAIN\\reader"); assert.equal(config.password, "network-password"); assert.equal(config.ssl_ca, "/certs/company.pem"); assert.equal(config.use_windows_auth, false);
    await auth.selectOption("kerberos"); assert.equal(await connection.getByLabel("Usuário", { exact: true }).getAttribute("placeholder"), "usuario@REALM"); await connection.getByLabel("Usuário", { exact: true }).fill("reader@EXAMPLE.COM");
    await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "Conexão testada" }).waitFor(); config = (await lastCall("connection.test")).params.config; assert.equal(config.sqlserver_auth_mode, "kerberos"); assert.equal(config.username, "reader@EXAMPLE.COM"); assert.equal(config.password, "network-password");
    await connection.getByLabel("Usuário", { exact: true }).fill(""); await connection.getByLabel("Senha", { exact: true }).fill(""); await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "Conexão testada" }).waitFor(); config = (await lastCall("connection.test")).params.config; assert.equal(config.username, ""); assert.equal(config.password, "");
    if (platform === "windows") { await auth.selectOption("windows"); assert.equal(await connection.getByLabel("Usuário", { exact: true }).count(), 0); assert.equal(await connection.getByLabel("Senha", { exact: true }).count(), 0); await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("status").filter({ hasText: "Conexão testada" }).waitFor(); assert.equal((await lastCall("connection.test")).params.config.use_windows_auth, true); }
    await noOverflow(connection); await connection.getByRole("button", { name: "Cancelar", exact: true }).click(); await connection.waitFor({ state: "detached" });
    console.log(`PASS ${platform}: integrated Windows availability, NTLM/Kerberos credentials, system ticket and CA request`);
  }
  await page.evaluate(() => { window.__SSH_TEST__.setPlatform("linux"); window.__SSH_OPEN_CONFIG__({ db_type: "sqlserver", name: "Legado Windows", host: "sql.internal", port: 1433, database: "esim", use_windows_auth: true }); });
  const unavailableAuth = connection.getByRole("combobox", { name: /^Autenticação/ }); await unavailableAuth.locator('option[value="ntlm"]').waitFor({ state: "attached" }); assert.equal(await unavailableAuth.inputValue(), "windows"); assert.equal(await unavailableAuth.locator('option[value="windows"]').evaluate(element => element.disabled), true);
  const beforeTests = await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "connection.test").length); await connection.getByRole("button", { name: "Testar conexão", exact: true }).click(); await connection.getByRole("alert").filter({ hasText: "Escolha uma autenticação disponível" }).waitFor(); assert.equal(await page.evaluate(() => window.__SSH_TEST__.calls.filter(call => call.method === "connection.test").length), beforeTests);
  await connection.getByRole("button", { name: "Cancelar", exact: true }).click(); await connection.waitFor({ state: "detached" });
  await openSettings(); await settings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await tunnel.waitFor();
  await page.keyboard.press("Escape"); await tunnel.waitFor({ state: "detached" }); assert.equal(await settings.count(), 1);
  await settings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await page.evaluate(() => window.__SSH_TEST__.resetTrust()); await tunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await trust.waitFor();
  await page.keyboard.press("Escape"); await trust.waitFor({ state: "detached" }); await tunnel.getByRole("alert").filter({ hasText: "cancelada" }).waitFor(); assert.equal(await tunnel.count(), 1); assert.equal(await settings.count(), 1);
  await page.keyboard.press("Escape"); await tunnel.waitFor({ state: "detached" }); assert.equal(await settings.count(), 1);
  await settings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await page.evaluate(() => window.__SSH_TEST__.holdSaves()); await tunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingSaveCount === 1);
  await page.evaluate(() => { document.body.tabIndex = -1; document.body.focus(); }); await page.keyboard.press("Escape");
  assert.equal(await tunnel.count(), 1); assert.equal(await settings.count(), 1); assert.equal(await page.evaluate(() => window.__SSH_TEST__.pendingSaveCount), 1);
  await page.evaluate(() => window.__SSH_TEST__.releaseSaves()); await tunnel.waitFor({ state: "detached" }); assert.equal(await settings.count(), 1); await page.keyboard.press("Escape"); await settings.waitFor({ state: "detached" });
  await page.evaluate(() => window.__SSH_OPEN_LEGACY__()); await page.locator("#legacy-confirm").waitFor(); await page.keyboard.press("Escape"); await page.locator("#legacy-confirm").waitFor({ state: "detached" });
  console.log("PASS modal shortcuts: Escape closes only the leaf, preserves SSH saves while focus is on body, and closes legacy confirmation");

  const popupPromise = page.waitForEvent("popup");
  await page.evaluate(async () => {
    const { registerDocument, copyRootPresentation } = await import("/src/documentWindows.ts"), popup = window.open("about:blank", "ssh-popout-test");
    if (!popup) throw new Error("Fixture popout was not created");
    window.__SSH_POPOUT_RELEASE__ = registerDocument(popup.document); copyRootPresentation(document, popup.document);
    for (const style of document.head.querySelectorAll("style")) popup.document.head.appendChild(style.cloneNode(true));
    popup.document.body.innerHTML = '<button id="open-settings">Open settings</button>';
    popup.document.getElementById("open-settings").onclick = () => [...document.querySelectorAll("#root > button")].find(button => button.textContent === "Configurações").click();
    window.__SSH_ATTACH_WINDOW__(popup); popup.focus();
  });
  const popup = await popupPromise; await popup.bringToFront(); await popup.locator("#open-settings").click();
  const popSettings = popup.getByRole("dialog", { name: "Configurações", exact: true }), popTunnel = popup.locator(".ssh-tunnel-dialog"), popTrust = popup.getByRole("dialog", { name: "Confirmar servidor SSH" });
  await popSettings.waitFor(); assert.equal(await settings.count(), 0); await popSettings.getByRole("button", { name: "Túneis SSH", exact: true }).click(); await popSettings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await popTunnel.waitFor();
  await page.evaluate(() => window.__SSH_TEST__.resetTrust()); await popTunnel.getByRole("button", { name: "Testar túnel", exact: true }).click(); await popTrust.waitFor(); await popup.keyboard.press("Escape"); await popTrust.waitFor({ state: "detached" }); await popTunnel.getByRole("alert").filter({ hasText: "cancelada" }).waitFor(); assert.equal(await popSettings.count(), 1);
  await popup.keyboard.press("Escape"); await popTunnel.waitFor({ state: "detached" }); await popSettings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await page.evaluate(() => window.__SSH_TEST__.holdSaves()); await popTunnel.getByRole("button", { name: "Salvar", exact: true }).click(); await page.waitForFunction(() => window.__SSH_TEST__.pendingSaveCount === 1);
  await popup.evaluate(() => { document.body.tabIndex = -1; document.body.focus(); }); await popup.keyboard.press("Escape"); assert.equal(await popTunnel.count(), 1); assert.equal(await popSettings.count(), 1);
  await page.evaluate(() => window.__SSH_TEST__.releaseSaves()); await popTunnel.waitFor({ state: "detached" }); await popup.keyboard.press("Escape"); await popSettings.waitFor({ state: "detached" }); await popup.close(); await page.evaluate(() => window.__SSH_POPOUT_RELEASE__());
  console.log("PASS popout: configuration/tunnel/fingerprint portals and leaf Escape stay in the focused document, including busy saves");
  await page.setViewportSize({ width: 420, height: 740 });
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme); await openSettings(); await noOverflow(settings);
    await settings.locator('.ssh-tunnel-list button[aria-label^="Editar túnel"]').click(); await tunnel.waitFor(); await noOverflow(tunnel); const bounds = await tunnel.boundingBox(); assert(bounds.width <= 420 && bounds.x >= 0 && bounds.x + bounds.width <= 420);
    await tunnel.getByRole("button", { name: "Cancelar", exact: true }).click(); await tunnel.waitFor({ state: "detached" }); await settings.getByRole("button", { name: "Fechar", exact: true }).last().click(); await settings.waitFor({ state: "detached" });
  }
  console.log("PASS narrow viewport: settings and long tunnel labels remain inside the window in both themes");
  assert.deepEqual(errors, []);
} finally { await browser?.close(); await server.close(); }
