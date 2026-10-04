import {invoke,isTauri} from "@tauri-apps/api/core";
import {listen} from "@tauri-apps/api/event";
import {acceptStartupSnapshot,INITIAL_STARTUP,STARTUP_MESSAGES,STARTUP_PHASES,type StartupPhase,type StartupSnapshot} from "./splashProtocol";

const shell=document.querySelector<HTMLElement>(".splash")!;
const status=document.getElementById("status")!,version=document.getElementById("version")!,detail=document.getElementById("detail")!;
const retry=document.getElementById("retry") as HTMLButtonElement;
const actions=document.getElementById("error-actions")!;
let snapshot=INITIAL_STARTUP;
function render(incoming:StartupSnapshot){
  snapshot=acceptStartupSnapshot(snapshot,incoming);
  shell.dataset.phase=snapshot.phase;
  status.textContent=snapshot.message;
  version.textContent=snapshot.version ? `v${snapshot.version}` : "DESKTOP";
  actions.hidden=snapshot.phase !== "error";
  retry.disabled=false;
  detail.textContent=snapshot.phase === "error" ? "Tente novamente ou feche o aplicativo." : "";
  const index=STARTUP_PHASES.indexOf(snapshot.phase as Exclude<StartupPhase,"error">);
  shell.querySelectorAll<HTMLElement>("[data-step]").forEach((step,i)=>{step.classList.toggle("complete",i < index);step.classList.toggle("current",i === index);});
}
async function exit(){if(isTauri())await invoke("splash_exit");}
document.getElementById("exit")!.addEventListener("click",()=>void exit().catch(()=>{status.textContent="Não foi possível encerrar. Use Alt+F4 para fechar o aplicativo.";}));
document.getElementById("quit")!.addEventListener("click",()=>void exit().catch(()=>{status.textContent="Não foi possível encerrar. Use Alt+F4 para fechar o aplicativo.";}));
retry.addEventListener("click",()=>{
  if(!isTauri())return;
  retry.disabled=true;
  void invoke<StartupSnapshot>("splash_retry").then(render).catch(()=>{retry.disabled=false;status.textContent="Não foi possível reiniciar a interface. Feche o aplicativo e abra novamente.";});
});
async function connect(){
  await listen<StartupSnapshot>("splash-state",event=>render(event.payload));
  render(await invoke<StartupSnapshot>("splash_state"));
}
if(isTauri())void connect().catch(()=>render({...snapshot,phase:"error",message:"Não foi possível acompanhar a inicialização. Feche o aplicativo e abra novamente."}));
else {
  // Static previews only in development; no manufactured progress in the application.
  const requested=import.meta.env.DEV ? new URLSearchParams(location.search).get("preview") : null;
  const phase:StartupPhase=requested === "error" || STARTUP_PHASES.includes(requested as typeof STARTUP_PHASES[number]) ? requested as StartupPhase : "frontend";
  render({...INITIAL_STARTUP,phase,message:phase === "error" ? "Não foi possível iniciar o ambiente Python. Verifique a instalação e tente novamente." : STARTUP_MESSAGES[phase]});
  version.textContent="PRÉVIA";
  document.getElementById("exit")!.setAttribute("disabled","");
  document.getElementById("quit")!.setAttribute("disabled","");
  retry.disabled=true;
}
