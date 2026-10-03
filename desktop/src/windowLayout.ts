/** Main-window geometry is private workspace metadata, always in physical pixels. */
export interface MainWindowLayout {
  version: 1;
  position: {x:number;y:number};
  size: {width:number;height:number};
  scaleFactor: number;
  maximized: boolean;
}
export interface WindowMonitor {
  position: {x:number;y:number};
  size: {width:number;height:number};
  workArea?: {position:{x:number;y:number};size:{width:number;height:number}};
  scaleFactor: number;
}
export interface WindowBounds {
  position: {x:number;y:number};
  size: {width:number;height:number};
  outerSize: {width:number;height:number};
  scaleFactor: number;
  maximized: boolean;
  minimized: boolean;
}
export interface WindowRestorePlan {
  layout: MainWindowLayout;
  minimum: {width:number;height:number};
}
export interface WindowLayoutPort {
  bounds(): Promise<WindowBounds>;
  monitors(): Promise<WindowMonitor[]>;
  apply(plan: WindowRestorePlan): Promise<void>;
}

function record(value:unknown):Record<string,unknown>|undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string,unknown> : undefined;
}
function finite(value:unknown):value is number {return typeof value === "number" && Number.isFinite(value);}
function scale(value:number):number {return Number.isFinite(value) && value >= .25 && value <= 8 ? value : 1;}
export function normalizeMainWindowLayout(value:unknown):MainWindowLayout|undefined {
  const item=record(value),position=record(item?.position),size=record(item?.size);
  if(item?.version !== 1 || !position || !size || !finite(position.x) || !finite(position.y) ||
    !finite(size.width) || !finite(size.height) || size.width <= 0 || size.height <= 0 ||
    !finite(item.scaleFactor) || item.scaleFactor < .25 || item.scaleFactor > 8 || typeof item.maximized !== "boolean")return undefined;
  return {version:1,position:{x:Math.round(position.x),y:Math.round(position.y)},
    size:{width:Math.max(1,Math.round(size.width)),height:Math.max(1,Math.round(size.height))},scaleFactor:item.scaleFactor,maximized:item.maximized};
}
function area(monitor:WindowMonitor) {
  const work=monitor.workArea;
  return work && finite(work.position.x) && finite(work.position.y) && finite(work.size.width) && finite(work.size.height) && work.size.width>0 && work.size.height>0
    ? work : {position:monitor.position,size:monitor.size};
}
function validMonitor(monitor:WindowMonitor) {
  return finite(monitor.position?.x) && finite(monitor.position?.y) && finite(monitor.size?.width) && finite(monitor.size?.height) && monitor.size.width>0 && monitor.size.height>0;
}
function monitorFor(layout:MainWindowLayout,monitors:WindowMonitor[]):WindowMonitor|undefined {
  const list=monitors.filter(validMonitor),{x,y}=layout.position,{width,height}=layout.size;
  let result:WindowMonitor|undefined,largest=-1,closest=Infinity;
  for(const monitor of list){
    const work=area(monitor),left=work.position.x,top=work.position.y,right=left+work.size.width,bottom=top+work.size.height;
    const overlap=Math.max(0,Math.min(x+width,right)-Math.max(x,left))*Math.max(0,Math.min(y+height,bottom)-Math.max(y,top));
    const centerX=x+width/2,centerY=y+height/2;
    const distance=(centerX-Math.max(left,Math.min(centerX,right)))**2+(centerY-Math.max(top,Math.min(centerY,bottom)))**2;
    if(overlap>largest || (overlap===largest && distance<closest)){result=monitor;largest=overlap;closest=distance;}
  }
  return result;
}
function clamp(value:number,min:number,max:number){return Math.max(min,Math.min(value,max));}

/** Keeps the title bar reachable after unplugging a monitor or changing desktop DPI. */
export function planWindowRestore(saved:MainWindowLayout,monitors:WindowMonitor[],frame:{width:number;height:number;scaleFactor?:number}={width:0,height:0}):WindowRestorePlan {
  const monitor=monitorFor(saved,monitors),targetScale=scale(monitor?.scaleFactor ?? saved.scaleFactor);
  const ratio=targetScale/saved.scaleFactor;
  const frameScale=targetScale/scale(frame.scaleFactor ?? targetScale);
  const frameWidth=Math.max(0,Math.round(Number.isFinite(frame.width) ? frame.width*frameScale : 0));
  const frameHeight=Math.max(0,Math.round(Number.isFinite(frame.height) ? frame.height*frameScale : 0));
  const work=monitor ? area(monitor) : undefined;
  const maximum={width:work ? Math.max(1,Math.floor(work.size.width-frameWidth)) : 100_000,
    height:work ? Math.max(1,Math.floor(work.size.height-frameHeight)) : 100_000};
  const minimum={width:Math.min(maximum.width,Math.round(960*targetScale)),height:Math.min(maximum.height,Math.round(640*targetScale))};
  const size={width:clamp(Math.round(saved.size.width*ratio),minimum.width,maximum.width),
    height:clamp(Math.round(saved.size.height*ratio),minimum.height,maximum.height)};
  const position=work ? {x:Math.round(clamp(saved.position.x,work.position.x,work.position.x+maximum.width-size.width)),
    y:Math.round(clamp(saved.position.y,work.position.y,work.position.y+maximum.height-size.height))} : saved.position;
  return {layout:{version:1,position,size,scaleFactor:targetScale,maximized:saved.maximized},minimum};
}
export function sameWindowLayout(left:MainWindowLayout|undefined,right:MainWindowLayout|undefined):boolean {
  return left===right || !!left && !!right && left.position.x===right.position.x && left.position.y===right.position.y &&
    left.size.width===right.size.width && left.size.height===right.size.height && left.scaleFactor===right.scaleFactor && left.maximized===right.maximized;
}
function fromBounds(bounds:WindowBounds):MainWindowLayout|undefined {
  return normalizeMainWindowLayout({version:1,position:bounds.position,size:bounds.size,scaleFactor:bounds.scaleFactor,maximized:bounds.maximized});
}

/** Serializes native reads, retaining restored (normal) bounds while max/minimized. */
export class WindowLayoutController {
  private latest?: MainWindowLayout;
  private pending:Promise<unknown>=Promise.resolve();
  restoring=false;
  constructor(private readonly port:WindowLayoutPort){}
  private serialize<T>(operation:()=>Promise<T>):Promise<T>{
    const result=this.pending.then(operation,operation);this.pending=result.catch(()=>{});return result;
  }
  restore(initial:unknown):Promise<MainWindowLayout|undefined>{
    this.restoring=true;
    return this.serialize(async()=>{
      try {
        const [bounds,monitors]=await Promise.all([this.port.bounds(),this.port.monitors()]);
        const saved=normalizeMainWindowLayout(initial);
        const baseline=saved ?? fromBounds(bounds);
        if(!baseline)return undefined;
        const frame={width:bounds.outerSize.width-bounds.size.width,height:bounds.outerSize.height-bounds.size.height,scaleFactor:bounds.scaleFactor};
        const plan=planWindowRestore(baseline,monitors,frame);
        // Store normal bounds before maximizing so the next resize cannot replace them.
        this.latest=plan.layout;
        await this.port.apply(plan);
        // Maximization emits asynchronous resize events on some window managers.
        // Keep known normal bounds instead of sampling that transition.
        if(plan.layout.maximized)return this.latest;
        return await this.read();
      } finally {this.restoring=false;}
    });
  }
  capture():Promise<MainWindowLayout|undefined>{return this.serialize(()=>this.read());}
  private async read():Promise<MainWindowLayout|undefined>{
    const bounds=await this.port.bounds();
    if(bounds.minimized)return this.latest;
    if(bounds.maximized && this.latest){
      if(!this.latest.maximized)this.latest={...this.latest,maximized:true};
      return this.latest;
    }
    const candidate=fromBounds(bounds);
    if(candidate && !sameWindowLayout(candidate,this.latest))this.latest=candidate;
    return this.latest;
  }
}
