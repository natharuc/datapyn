export const STARTUP_PHASES = ["frontend", "runtime", "workspace", "editor", "ready"] as const;
export type StartupPhase = typeof STARTUP_PHASES[number] | "error";
export interface StartupSnapshot {phase:StartupPhase;message:string;attempt:number;version:string}
export const INITIAL_STARTUP:StartupSnapshot = {phase:"frontend",message:"Iniciando DataPyn…",attempt:0,version:""};
export const STARTUP_MESSAGES:Record<StartupPhase,string> = {
  frontend:"Preparando a interface…",
  runtime:"Iniciando o ambiente Python…",
  workspace:"Restaurando suas análises…",
  editor:"Preparando o editor…",
  ready:"Pronto.",
  error:"Não foi possível iniciar o DataPyn.",
};

/** Events and snapshot replies may arrive in either order. Never rewind a boot. */
export function acceptStartupSnapshot(current:StartupSnapshot,incoming:StartupSnapshot):StartupSnapshot {
  if(incoming.attempt < current.attempt)return current;
  if(incoming.attempt > current.attempt)return incoming;
  if(current.phase === "ready" || current.phase === "error")return current;
  if(incoming.phase !== "error" && STARTUP_PHASES.indexOf(incoming.phase) < STARTUP_PHASES.indexOf(current.phase))return current;
  if(incoming.phase === current.phase && incoming.message === current.message && incoming.version === current.version)return current;
  return incoming;
}

interface StartupBlock {id:string;collapsed?:boolean;cell_type?:string}
/** Prepare one usable editor without mounting every restored document/block. */
export function startupEditorId(blocks:readonly StartupBlock[],focusedId?:string,maximizedId?:string):string|undefined {
  const eligible=blocks.filter(block=>!block.collapsed && (!maximizedId || block.id === maximizedId) && (!block.cell_type || block.cell_type === "code"));
  return (eligible.find(block=>block.id === focusedId) ?? eligible[0])?.id;
}

export function startupPhase(input:{runtime:"connecting"|"ready"|"unavailable";error:string;profile:boolean;layout:boolean;editor:boolean;files:boolean}):StartupPhase {
  if(input.runtime === "unavailable" || input.error)return "error";
  if(input.runtime !== "ready")return "runtime";
  if(!input.profile)return "workspace";
  if(!input.layout || !input.editor || !input.files)return "editor";
  return "ready";
}
